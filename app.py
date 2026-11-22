import os
import sys
import json
import time
import math
import sqlite3
import threading
import subprocess
import shutil
import secrets
import webbrowser
import logging
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode, urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "ScarClipScheduler"
APP_VERSION = "2.0.14"
MAX_INTERVAL_MINUTES = 24 * 60
APP_DIR = Path(__file__).resolve().parent
ASSET_DIR = APP_DIR / "assets"
APP_LOGO_PATH = ASSET_DIR / "scarclipscheduler-logo.png"
APP_ICON_PATH = ASSET_DIR / "scarclipscheduler.ico"
GRAPH_VERSION = "v27.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
DEFAULT_FOLDER = str(Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Programs" / "StreamSnip AI" / "source" / "out")
DEFAULT_PAGE_ID = ""
YT_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
LOCAL_DIR = Path(os.environ.get("SCARCLIPSCHEDULER_DATA_DIR") or (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME))
LOCAL_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = LOCAL_DIR / "queue.db"
SETTINGS_PATH = LOCAL_DIR / "settings.json"
CREDENTIALS_PATH = LOCAL_DIR / "credentials.json"
YT_TOKEN_PATH = LOCAL_DIR / "youtube_token.json"
LOG_PATH = LOCAL_DIR / "app.log"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger(APP_NAME)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def clip_sidecar_path(video_path):
    """Return the TXT metadata file paired with an MP4 by its exact basename."""
    return Path(video_path).with_suffix(".txt")


def clip_selection_summary(selected_count):
    """Explain whether the queue action targets one clip, a batch, or all clips."""
    if selected_count <= 0:
        return "0 selected | entire queue will be scheduled"
    if selected_count == 1:
        return "1 selected | one clip will be scheduled"
    return f"{selected_count} selected | batch scheduling"


def parse_txt(path):
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = raw.splitlines()
    nonempty = [i for i, line in enumerate(lines) if line.strip()]
    if not nonempty:
        return Path(path).stem, ""
    first = nonempty[0]
    title = lines[first].strip()
    description = "\n".join(lines[first + 1:]).strip()
    if len(title) > 100:
        title = title[:97].rstrip() + "..."
    return title, description


def ffprobe_path():
    candidate = shutil.which("ffprobe")
    if candidate:
        return candidate
    known = Path(r"C:\Program Files\Jellyfin\Server\ffprobe.exe")
    return str(known) if known.exists() else None


def probe_video(path):
    exe = ffprobe_path()
    if not exe:
        return None, None, None, None
    try:
        result = subprocess.run(
            [
                exe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-show_entries", "format=duration", "-of", "json", str(path)
            ],
            capture_output=True, text=True, timeout=20, check=True
        )
        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        duration = float((data.get("format") or {}).get("duration") or 0)
        fb_ok = bool(width > 0 and height > 0 and width * 16 == height * 9 and 4 <= duration <= 60)
        return width, height, duration, fb_ok
    except Exception as exc:
        logger.warning("ffprobe failed for %s: %s", path, exc)
        return None, None, None, None


def local_now():
    return datetime.now().astimezone()


def validate_interval_minutes(value):
    """Validate the supported posting interval: five minutes through 24 hours."""
    try:
        interval = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Interval must be a whole number of minutes.") from exc
    if not 5 <= interval <= MAX_INTERVAL_MINUTES:
        raise ValueError(f"Interval must be between 5 minutes and {MAX_INTERVAL_MINUTES} minutes (24 hours).")
    return interval


def next_pacific_midnight(moment=None):
    moment = moment or local_now()
    pacific = ZoneInfo("America/Los_Angeles")
    now_pacific = moment.astimezone(pacific)
    next_day = now_pacific.date() + timedelta(days=1)
    reset_pacific = datetime(next_day.year, next_day.month, next_day.day, 0, 5, tzinfo=pacific)
    return reset_pacific.astimezone(moment.tzinfo)


def allocate_youtube_publish_slots(rows, start, interval, now=None):
    """Allocate requested slots while preserving accepted destinations.

    Existing accepted YouTube posts are never rewritten. Pending destinations with
    an already reserved future retry slot keep it; new pending destinations begin
    at the user's chosen start time. The YouTube daily quota is enforced per
    Pacific calendar day.
    """
    interval = validate_interval_minutes(interval)
    now = now or local_now()
    if start.tzinfo is None:
        start = start.astimezone()
    minimum_publish = now + timedelta(minutes=15)
    pacific = ZoneInfo("America/Los_Angeles")
    accepted = {"scheduled", "published"}
    future_slots = []
    daily_counts = {}
    needs_slot = []

    for row in rows:
        status = str(row.get("yt_status") or "Pending").strip().lower()
        raw_time = row.get("publish_at")
        try:
            publish_at = datetime.fromisoformat(raw_time).astimezone() if raw_time else None
        except (TypeError, ValueError, OverflowError):
            publish_at = None

        if status in accepted:
            # An accepted post is never re-uploaded or rescheduled by this helper.
            if publish_at and publish_at > now:
                day = publish_at.astimezone(pacific).date()
                daily_counts[day] = daily_counts.get(day, 0) + 1
            continue

        if publish_at and publish_at >= minimum_publish:
            future_slots.append(publish_at)
            day = publish_at.astimezone(pacific).date()
            daily_counts[day] = daily_counts.get(day, 0) + 1
        else:
            needs_slot.append(row)

    if not needs_slot:
        return {}

    base = max(
        [start, minimum_publish] +
        [slot.astimezone(start.tzinfo) + timedelta(minutes=int(interval)) for slot in future_slots]
    )
    cursor = base.astimezone(pacific)
    assignments = {}

    for row in needs_slot:
        while daily_counts.get(cursor.date(), 0) >= 100:
            next_day = cursor.date() + timedelta(days=1)
            selected_clock = start.astimezone(pacific).timetz().replace(tzinfo=None)
            cursor = datetime.combine(next_day, selected_clock, tzinfo=pacific)

        path = str(row["path"])
        assignments[path] = cursor.astimezone(start.tzinfo).isoformat()
        day = cursor.date()
        daily_counts[day] = daily_counts.get(day, 0) + 1
        cursor += timedelta(minutes=int(interval))

    return assignments


def suggested_start(count, youtube_enabled=True):
    now = local_now()
    # Large queues start after the next YouTube daily quota reset, with time to upload
    # the first 100 items before their scheduled publication window.
    if youtube_enabled and count > 100:
        return next_pacific_midnight(now) + timedelta(hours=4)
    # A four-hour staging window is deliberately conservative for large folders.
    return now + (timedelta(hours=4) if count > 40 else timedelta(minutes=45))


def fmt_dt(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


class FacebookCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        self.server.oauth_result = {
            "code": (params.get("code") or [None])[0],
            "state": (params.get("state") or [None])[0],
            "error": (params.get("error_description") or params.get("error") or [None])[0],
        }
        body = b"<html><body style='font-family:Arial;padding:40px'><h2>Facebook connection response received.</h2><p>You can return to ScarClipScheduler.</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class SchedulerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"ScarClipScheduler {APP_VERSION}")
        # Keep a practical minimum restored size: the app cannot be squeezed
        # into a layout where controls overlap. Windows' normal minimize button
        # remains available in the title bar.
        self.root.geometry("1280x900")
        self.root.minsize(1120, 760)
        self.root.resizable(True, True)
        self.header_logo = None
        self.apply_app_icon()
        self.stop_event = threading.Event()
        self.worker = None
        self.scan_worker = None
        self.verification_worker = None
        self.db_lock = threading.Lock()
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_db()

        self.settings = read_json(SETTINGS_PATH, {
            "folder": DEFAULT_FOLDER,
            "page_id": DEFAULT_PAGE_ID,
            "business_id": "",
            "fb_selected_page_ids": [],
            "client_secrets": "",
            "meta_app_id": "",
            "meta_app_secret": "",
            "interval": 5,
            "youtube_enabled": True,
            "facebook_enabled": True,
            "youtube_ai": False,
            "facebook_ai": False,
            "category_id": "20",
            "made_for_kids": False,
            "start_at": "",
        })
        self.secrets = read_json(CREDENTIALS_PATH, {
            "fb_page_access_token": "",
            "fb_page_name": "",
            "fb_page_id": "",
            "yt_channel_title": "",
            "yt_channel_id": "",
        })

        self.folder_var = tk.StringVar(value=self.settings.get("folder", DEFAULT_FOLDER))
        self.start_var = tk.StringVar(value=self.settings.get("start_at") or "")
        self.interval_var = tk.StringVar(value=str(self.settings.get("interval", 5)))
        self.youtube_var = tk.BooleanVar(value=self.settings.get("youtube_enabled", True))
        self.facebook_var = tk.BooleanVar(value=self.settings.get("facebook_enabled", True))
        self.youtube_ai_var = tk.BooleanVar(value=self.settings.get("youtube_ai", False))
        self.facebook_ai_var = tk.BooleanVar(value=self.settings.get("facebook_ai", False))
        self.made_for_kids_var = tk.BooleanVar(value=self.settings.get("made_for_kids", False))
        self.rights_confirm_var = tk.BooleanVar(value=False)
        self.page_id_var = tk.StringVar(value=self.settings.get("page_id", DEFAULT_PAGE_ID))
        self.business_id_var = tk.StringVar(value=self.settings.get("business_id", ""))
        self.fb_page_vars = {}
        self.client_secrets_var = tk.StringVar(value=self.settings.get("client_secrets", ""))
        self.meta_app_id_var = tk.StringVar(value=self.settings.get("meta_app_id", ""))
        self.meta_app_secret_var = tk.StringVar(value=self.settings.get("meta_app_secret", ""))
        self.category_var = tk.StringVar(value=self.settings.get("category_id", "20"))
        self.connection_status_var = tk.StringVar(value="Checking connections…")
        self.queue_summary_var = tk.StringVar(value="Scan the clip folder to load your videos.")
        self.selection_title_var = tk.StringVar()
        self.selection_desc = None
        self.selected_path = None
        self.txt_preview_cache = {}
        self.build_ui()
        self.refresh_connections()
        self.refresh_table()
        self.root.after(1000, self.refresh_table)
        # Verify due posts on startup and periodically while the scheduler is open.
        self.root.after(12000, lambda: self.check_publication_status(show_dialog=False))
        self.root.after(15 * 60 * 1000, self.auto_check_publication_status)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def apply_app_icon(self):
        """Apply the bundled ScarClipScheduler mark to the window and taskbar."""
        try:
            if APP_ICON_PATH.is_file():
                self.root.iconbitmap(default=str(APP_ICON_PATH))
        except (tk.TclError, OSError):
            pass
        try:
            if APP_LOGO_PATH.is_file():
                self.header_logo = tk.PhotoImage(file=str(APP_LOGO_PATH)).subsample(8, 8)
                self.root.iconphoto(True, self.header_logo)
        except (tk.TclError, OSError):
            self.header_logo = None

    def create_db(self):
        with self.db_lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS clips (
                    path TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    duration REAL,
                    fb_ok INTEGER,
                    publish_at TEXT,
                    yt_status TEXT NOT NULL DEFAULT 'Pending',
                    fb_status TEXT NOT NULL DEFAULT 'Pending',
                    yt_video_id TEXT,
                    fb_video_id TEXT,
                    yt_error TEXT,
                    fb_error TEXT,
                    modified REAL
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS facebook_page_jobs (
                    path TEXT NOT NULL,
                    page_id TEXT NOT NULL,
                    page_name TEXT NOT NULL,
                    publish_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pending',
                    video_id TEXT,
                    error TEXT,
                    submitted_at TEXT,
                    PRIMARY KEY (path, page_id)
                )
            """)
            columns = {
                row[1] for row in self.conn.execute("PRAGMA table_info(facebook_page_jobs)").fetchall()
            }
            if "submitted_at" not in columns:
                self.conn.execute("ALTER TABLE facebook_page_jobs ADD COLUMN submitted_at TEXT")
            self.conn.commit()

    def build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Deep navy surfaces with vivid violet/blue accents.
        self.colors = {
            "app_bg": "#0B1020",
            "surface": "#121A2D",
            "surface_soft": "#1B2640",
            "surface_alt": "#202B49",
            "text": "#F1F5FF",
            "muted": "#9AA8C4",
            "accent": "#8B5CF6",
            "accent_hover": "#7544E8",
            "accent_soft": "#302153",
            "border": "#293653",
            "danger": "#FB7185",
            "success": "#34D399",
            "warning": "#FBBF24",
            "info": "#60A5FA",
        }
        c = self.colors
        self.root.configure(background=c["app_bg"])

        style.configure(".", font=("Segoe UI", 9), foreground=c["text"])
        style.configure("TFrame", background=c["app_bg"])
        style.configure("Card.TFrame", background=c["surface"])
        style.configure("TLabel", background=c["app_bg"], foreground=c["text"])
        style.configure(
            "Title.TLabel", font=("Segoe UI Semibold", 19),
            foreground=c["text"], background=c["app_bg"]
        )
        style.configure(
            "Sub.TLabel", font=("Segoe UI", 9),
            foreground=c["muted"], background=c["app_bg"]
        )
        style.configure(
            "Section.TLabel", font=("Segoe UI Semibold", 12),
            foreground=c["text"], background=c["app_bg"]
        )
        style.configure(
            "Eyebrow.TLabel", font=("Segoe UI Semibold", 8),
            foreground="#B9A5FF", background=c["app_bg"]
        )
        style.configure(
            "Version.TLabel", font=("Segoe UI Semibold", 9),
            foreground="#E9DFFF", background=c["accent_soft"], padding=(12, 7)
        )
        style.configure(
            "TLabelframe", background=c["surface"], foreground=c["text"],
            bordercolor=c["border"], relief="solid", borderwidth=1, padding=8
        )
        style.configure(
            "TLabelframe.Label", background=c["surface"],
            foreground="#BCA8FF", font=("Segoe UI Semibold", 9)
        )
        style.configure(
            "TButton", padding=(11, 8), background=c["surface_soft"],
            foreground=c["text"], bordercolor=c["border"], relief="flat",
            font=("Segoe UI Semibold", 9)
        )
        style.map(
            "TButton",
            background=[("active", c["surface_alt"]), ("pressed", c["surface_alt"])],
            foreground=[("disabled", "#66728D")]
        )
        style.configure(
            "Accent.TButton", padding=(14, 9), background=c["accent"],
            foreground="#FFFFFF", bordercolor=c["accent"], relief="flat",
            font=("Segoe UI Semibold", 9)
        )
        style.map(
            "Accent.TButton",
            background=[("active", c["accent_hover"]), ("pressed", c["accent_hover"])],
            foreground=[("disabled", "#D8D0EA")]
        )
        style.configure(
            "Danger.TButton", padding=(10, 8), background="#3A1D34",
            foreground="#FDA4AF", bordercolor="#713248", relief="flat"
        )
        style.configure(
            "Stop.TButton", padding=(14, 9), background="#4B2234",
            foreground="#FDA4AF", bordercolor="#844158", relief="flat",
            font=("Segoe UI Semibold", 9)
        )
        style.map(
            "Stop.TButton",
            background=[("active", "#612A43"), ("disabled", c["surface_soft"])],
            foreground=[("disabled", c["muted"])]
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#51233E")],
            foreground=[("disabled", "#8F7180")]
        )
        style.configure(
            "TCheckbutton", background=c["surface"], foreground=c["text"],
            padding=5, font=("Segoe UI", 9)
        )
        style.map(
            "TCheckbutton",
            background=[("active", c["surface"])],
            foreground=[("disabled", c["muted"])]
        )
        style.configure(
            "TEntry", fieldbackground=c["surface_alt"], foreground=c["text"],
            insertcolor=c["text"], bordercolor=c["border"], lightcolor=c["accent"],
            darkcolor=c["border"], padding=7
        )
        style.map(
            "TEntry",
            fieldbackground=[("readonly", c["surface_alt"])],
            bordercolor=[("focus", c["accent"])]
        )
        style.configure(
            "TSpinbox", fieldbackground=c["surface_alt"], foreground=c["text"],
            arrowcolor=c["muted"], bordercolor=c["border"], padding=6
        )
        style.configure(
            "TCombobox", fieldbackground=c["surface_alt"], foreground=c["text"],
            arrowcolor=c["muted"], bordercolor=c["border"], padding=7
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["surface_alt"]), ("focus", c["surface_alt"])],
            foreground=[("readonly", c["text"])],
            selectbackground=[("readonly", c["accent_soft"])],
            selectforeground=[("readonly", c["text"])]
        )
        style.configure("TNotebook", background=c["app_bg"], borderwidth=0, tabmargins=(0, 7, 0, 0))
        style.configure(
            "TNotebook.Tab", padding=(19, 11), background=c["surface"],
            foreground=c["muted"], bordercolor=c["border"],
            font=("Segoe UI Semibold", 9)
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", c["accent_soft"]), ("active", c["surface_alt"])],
            foreground=[("selected", "#E9DFFF"), ("active", c["text"])]
        )
        style.configure(
            "Treeview", rowheight=34, font=("Segoe UI", 9),
            background=c["surface"], fieldbackground=c["surface"],
            foreground=c["text"], bordercolor=c["border"],
            relief="flat"
        )
        style.configure(
            "Treeview.Heading", font=("Segoe UI Semibold", 9),
            background=c["surface_soft"], foreground="#CBD5EF",
            relief="flat", padding=(8, 10)
        )
        style.map(
            "Treeview",
            background=[("selected", c["accent_soft"])],
            foreground=[("selected", "#FFFFFF")]
        )
        style.configure(
            "Vertical.TScrollbar", troughcolor=c["app_bg"],
            background=c["surface_soft"], bordercolor=c["app_bg"],
            arrowcolor=c["muted"]
        )
        style.configure(
            "Horizontal.TScrollbar", troughcolor=c["app_bg"],
            background=c["surface_soft"], bordercolor=c["app_bg"],
            arrowcolor=c["muted"]
        )

        outer = ttk.Frame(self.root, padding=(20, 16))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))

        brand = ttk.Frame(header)
        brand.pack(side="left", fill="y")
        if self.header_logo is not None:
            ttk.Label(brand, image=self.header_logo, background=c["app_bg"]).pack(side="left", padx=(0, 12))
        brand_copy = ttk.Frame(brand)
        brand_copy.pack(side="left", fill="y", pady=(4, 0))
        ttk.Label(brand_copy, text="ScarClipScheduler", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            brand_copy, text="CLIP  /  SCHEDULE  /  SHARE",
            style="Eyebrow.TLabel"
        ).pack(anchor="w", pady=(1, 0))

        ttk.Label(
            header, text=f"DESKTOP APP  |  v{APP_VERSION}",
            style="Version.TLabel"
        ).pack(side="right", anchor="center", pady=(9, 0))
        ttk.Button(
            header, text="Quit", command=self.on_close, style="Danger.TButton"
        ).pack(side="right", padx=(0, 10), pady=(9, 0))

        divider = tk.Frame(outer, height=1, background=c["border"], bd=0, highlightthickness=0)
        divider.pack(fill="x", pady=(0, 12))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        self.publish_tab = ttk.Frame(notebook, padding=12)
        self.connections_tab = ttk.Frame(notebook, padding=14)
        self.logs_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.publish_tab, text="  Publishing queue  ")
        notebook.add(self.connections_tab, text="  Connections  ")
        notebook.add(self.logs_tab, text="  Activity log  ")
        self.notebook = notebook

        self.build_publish_tab()
        self.build_connections_tab()
        self.build_logs_tab()

    def build_publish_tab(self):
        tab = self.publish_tab
        intro = ttk.Frame(tab)
        intro.pack(fill="x", pady=(0, 10))
        ttk.Label(intro, text="Publishing workspace", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            intro,
            text="Review your clips, choose destinations and schedule the next batch.",
            style="Sub.TLabel"
        ).pack(anchor="w", pady=(2, 0))

        help_box = ttk.LabelFrame(tab, text="  HOW TO LOAD VIDEOS + TXT METADATA  ", padding=9)
        help_box.pack(fill="x", pady=(0, 8))
        ttk.Label(
            help_box,
            text=(
                "1. Put each MP4 and its TXT file together in the same folder. The names before the extensions "
                "must match exactly:\n"
                "   highlight_001.mp4   +   highlight_001.txt\n"
                "   highlight_002.mp4   +   highlight_002.txt\n"
                "2. Click Browse and choose that folder, then click Scan clips. Keep the files directly in the "
                "chosen folder (the scan does not search subfolders).\n"
                "3. In each TXT file, the first non-empty line is the video title; everything after it is the "
                "description. A missing TXT does not block the MP4: its filename becomes the title and the "
                "description starts blank."
            ),
            style="Sub.TLabel",
            justify="left",
            wraplength=1080
        ).pack(anchor="w")
        folder_box = ttk.LabelFrame(tab, text="  CLIP SOURCE  ", padding=10)
        folder_box.pack(fill="x", pady=(0, 8))
        ttk.Entry(folder_box, textvariable=self.folder_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(folder_box, text="Browse", command=self.browse_folder).pack(side="left", padx=3)
        ttk.Button(folder_box, text="Scan clips", command=self.scan_folder).pack(side="left", padx=3)
        ttk.Label(tab, textvariable=self.queue_summary_var).pack(anchor="w", pady=(0, 7))

        schedule_box = ttk.LabelFrame(tab, text="  PUBLISHING SCHEDULE  ", padding=10)
        schedule_box.pack(fill="x", pady=(0, 8))
        row1 = ttk.Frame(schedule_box)
        row1.pack(fill="x")
        ttk.Label(row1, text="First post (your Windows local time):").pack(side="left")
        ttk.Entry(row1, textvariable=self.start_var, width=19).pack(side="left", padx=(7, 14))
        ttk.Label(row1, text="Format: YYYY-MM-DD HH:MM").pack(side="left")
        ttk.Label(row1, text="Interval:").pack(side="left", padx=(22, 4))
        ttk.Spinbox(row1, from_=5, to=1440, width=6, textvariable=self.interval_var).pack(side="left")
        ttk.Label(row1, text="minutes").pack(side="left", padx=(4, 0))

        row2 = ttk.Frame(schedule_box)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(row2, text="Upload to YouTube Shorts", variable=self.youtube_var).pack(side="left")
        ttk.Checkbutton(row2, text="Upload to Facebook Page Reels", variable=self.facebook_var).pack(side="left", padx=(18, 0))
        ttk.Checkbutton(row2, text="YouTube AI disclosure", variable=self.youtube_ai_var).pack(side="left", padx=(22, 0))
        ttk.Checkbutton(row2, text="Facebook AI-generated flag", variable=self.facebook_ai_var).pack(side="left", padx=(12, 0))

        row3 = ttk.Frame(schedule_box)
        row3.pack(fill="x", pady=(7, 0))
        ttk.Label(row3, text="YouTube category:").pack(side="left")
        category = ttk.Combobox(
            row3, textvariable=self.category_var, width=18, state="readonly",
            values=["20 - Gaming", "22 - People & Blogs", "24 - Entertainment", "23 - Comedy", "26 - Howto & Style"]
        )
        category.pack(side="left", padx=(6, 14))
        category.set(next(
            (value for value in category["values"] if value.split(" - ")[0] == self.category_var.get()),
            category["values"][0]
        ))
        ttk.Checkbutton(row3, text="Made for kids", variable=self.made_for_kids_var).pack(side="left")
        ttk.Label(
            row3,
            text="Only mark AI when the video contains realistic AI-generated/altered content.",
            foreground="#9b5b00"
        ).pack(side="left", padx=(14, 0))

        ttk.Checkbutton(
            schedule_box,
            text="I confirm I own these clips or have permission to repost them, and that the uploads comply with platform rules.",
            variable=self.rights_confirm_var
        ).pack(anchor="w", pady=(7, 0))

        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Set recommended start time", command=self.set_recommended_start).pack(side="left")
        self.schedule_button = ttk.Button(actions, text="Schedule queue on selected platforms", command=self.start_scheduling, style="Accent.TButton")
        self.schedule_button.pack(side="left", padx=7)
        self.stop_button = ttk.Button(
            actions, text="Stop queue", command=self.stop_scheduling,
            state="disabled", style="Stop.TButton"
        )
        self.stop_button.pack(side="left")
        ttk.Button(actions, text="Export file cleanup report", command=self.export_cleanup_report).pack(side="right", padx=(0, 7))
        self.verification_button = ttk.Button(
            actions, text="Check publication status", command=self.check_publication_status
        )
        self.verification_button.pack(side="right", padx=(0, 7))
        ttk.Button(actions, text="Reset failed items", command=self.reset_failed).pack(side="right")

        table_frame = ttk.LabelFrame(tab, text="Detected clips", padding=5)
        table_frame.pack(fill="both", expand=True, pady=(2, 0))
        selection_bar = ttk.Frame(table_frame)
        selection_bar.pack(fill="x", pady=(0, 5))
        ttk.Button(selection_bar, text="Select all", command=self.select_all_clips).pack(side="left")
        ttk.Button(
            selection_bar, text="Delete from list", command=self.delete_selected_from_list,
            style="Danger.TButton"
        ).pack(side="left", padx=(6, 6))
        ttk.Button(selection_bar, text="Unselect all", command=self.unselect_all_clips).pack(side="left", padx=(0, 12))
        self.clip_selection_var = tk.StringVar(value="0 selected")
        ttk.Label(selection_bar, textvariable=self.clip_selection_var, style="Sub.TLabel").pack(side="left")
        ttk.Label(
            selection_bar,
            text="Click one row to edit | Ctrl+click adds/removes rows | Shift+click selects a range",
            style="Sub.TLabel"
        ).pack(side="right")
        columns = (
            "number", "queue_status", "file", "title", "description",
            "duration", "youtube", "facebook", "publish"
        )
        tree_shell = ttk.Frame(table_frame)
        tree_shell.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            tree_shell, columns=columns, show="headings",
            selectmode="extended", height=6
        )
        self.tree_path_by_id = {}
        self.tree.bind("<<TreeviewSelect>>", self.update_clip_selection_count, add="+")
        self.tree.heading("number", text="#")
        self.tree.heading("queue_status", text="Queue status")
        self.tree.heading("file", text="Video file")
        self.tree.heading("title", text="Editable title")
        self.tree.heading("description", text="Editable description")
        self.tree.heading("duration", text="Length")
        self.tree.heading("youtube", text="YouTube")
        self.tree.heading("facebook", text="Facebook")
        self.tree.heading("publish", text="Scheduled time")
        self.tree.column("number", width=40, minwidth=40, stretch=False, anchor="center")
        self.tree.column("queue_status", width=105, minwidth=100, stretch=False, anchor="center")
        self.tree.column("file", width=205, minwidth=160, anchor="w")
        self.tree.column("title", width=245, minwidth=180, anchor="w")
        self.tree.column("description", width=340, minwidth=220, anchor="w")
        self.tree.column("duration", width=58, stretch=False, anchor="center")
        self.tree.column("youtube", width=82, stretch=False, anchor="center")
        self.tree.column("facebook", width=82, stretch=False, anchor="center")
        self.tree.column("publish", width=132, stretch=False, anchor="center")
        yscroll = ttk.Scrollbar(tree_shell, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(tree_shell, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        tree_shell.grid_rowconfigure(0, weight=1)
        tree_shell.grid_columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.on_select, add="+")
        self.tree.bind("<Double-1>", self.focus_metadata_editor, add="+")
        self.tree.tag_configure("error", foreground=self.colors["danger"])
        self.tree.tag_configure("scheduled", foreground=self.colors["success"])
        self.tree.tag_configure("published", foreground=self.colors["success"])
        self.tree.tag_configure("partial", foreground=self.colors["warning"])
        self.tree.tag_configure("pending", foreground=self.colors["muted"])

        editor = ttk.LabelFrame(tab, text="  EDIT SELECTED CLIP  ", padding=9)
        editor.pack(fill="x", pady=(8, 0))
        edit_top = ttk.Frame(editor)
        edit_top.pack(fill="x")
        ttk.Label(edit_top, text="Title (max 100 characters):").pack(side="left")
        self.selection_title_entry = ttk.Entry(edit_top, textvariable=self.selection_title_var)
        self.selection_title_entry.pack(side="left", fill="x", expand=True, padx=7)
        ttk.Button(edit_top, text="Save metadata", command=self.save_selected_metadata).pack(side="right")
        ttk.Label(editor, text="Description").pack(anchor="w", pady=(6, 2))
        self.selection_desc = tk.Text(
            editor, height=3, wrap="word", font=("Segoe UI", 9),
            background=self.colors["surface"], foreground=self.colors["text"],
            insertbackground=self.colors["accent"], relief="flat",
            highlightthickness=1, highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"], selectbackground=self.colors["accent_soft"],
            padx=10, pady=8
        )
        self.selection_desc.pack(fill="x")
        ttk.Label(
            editor,
            text="The editor changes only the first highlighted clip. Selecting multiple rows is for batch scheduling or removing several queue entries.",
            style="Sub.TLabel"
        ).pack(anchor="w", pady=(5, 0))

    def build_connections_tab(self):
        # Scrollable work area: at the minimum window size all controls remain
        # usable, and the user can scroll if Windows scaling makes content taller.
        host = self.connections_tab
        shell = ttk.Frame(host)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(
            shell, highlightthickness=0, bd=0,
            background=self.colors["app_bg"], yscrollincrement=24
        )
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        content = ttk.Frame(canvas, padding=12)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        self.connections_canvas = canvas
        self.connections_content = content

        def update_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_content_width(event):
            canvas.itemconfigure(window_id, width=event.width)

        content.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", fit_content_width)
        self.root.bind_all("<MouseWheel>", self._scroll_connections, add="+")

        tab = content
        ttk.Label(tab, text="Account connections", style="Title.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(
            tab,
            text="Credentials stay on this Windows account. This app uses the official free platform APIs; it does not use browser-cookie scraping.",
            wraplength=850
        ).pack(anchor="w", pady=(0, 12))

        yt = ttk.LabelFrame(tab, text="YouTube channel", padding=10)
        yt.pack(fill="x", pady=(0, 12))
        ttk.Label(yt, text="OAuth Desktop client JSON file (client_secrets.json):").grid(row=0, column=0, sticky="w")
        ttk.Entry(yt, textvariable=self.client_secrets_var).grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=4)
        ttk.Button(yt, text="Browse", command=self.browse_client_secrets).grid(row=1, column=1, padx=3)
        ttk.Button(yt, text="Connect YouTube", command=self.connect_youtube, style="Accent.TButton").grid(row=1, column=2, padx=3)
        self.yt_status_label = ttk.Label(yt, text="Not connected")
        self.yt_status_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(5, 0))
        yt.columnconfigure(0, weight=1)

        fb = ttk.LabelFrame(tab, text="Facebook Business Portfolio / Page Reels", padding=10)
        fb.pack(fill="x", pady=(0, 12))
        ttk.Label(fb, text="Meta App ID:").grid(row=0, column=0, sticky="w")
        ttk.Entry(fb, textvariable=self.meta_app_id_var, width=25).grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=4)
        ttk.Label(fb, text="Meta App Secret:").grid(row=0, column=1, sticky="w")
        ttk.Entry(fb, textvariable=self.meta_app_secret_var, show="•", width=30).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=4)
        ttk.Label(fb, text="Business Portfolio ID:").grid(row=0, column=2, sticky="w")
        ttk.Entry(fb, textvariable=self.business_id_var, width=24).grid(row=1, column=2, sticky="ew", pady=4)
        ttk.Button(fb, text="Connect & Load Business Pages", command=self.connect_facebook, style="Accent.TButton").grid(row=2, column=0, sticky="w", pady=(7, 0))
        self.fb_status_label = ttk.Label(fb, text="Not connected — enter Meta app and Business Portfolio details.")
        self.fb_status_label.grid(row=2, column=1, columnspan=2, sticky="w", pady=(7, 0))
        for col in range(3):
            fb.columnconfigure(col, weight=1)

        page_box = ttk.LabelFrame(fb, text="Select Facebook Pages for publishing", padding=8)
        page_box.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Label(page_box, text="Connect to load all Pages. Select the Pages that should receive each Reel.").pack(anchor="w")
        self.fb_page_checks = ttk.Frame(page_box)
        self.fb_page_checks.pack(fill="x", pady=(5, 0))

        info = ttk.LabelFrame(tab, text="Required one-time setup", padding=10)
        info.pack(fill="both", expand=True)
        ttk.Label(
            info,
            text=(
                "YOUTUBE\n"
                "1. Create a project at console.cloud.google.com and enable YouTube Data API v3.\n"
                "2. Configure OAuth consent, add your Google account as a test user if the app is in Testing, "
                "then create an OAuth Client ID of type Desktop app.\n"
                "3. Download its JSON file and select it above. Connect YouTube and approve the upload permission.\n"
                "4. For unattended long-term use, set the OAuth app publishing status to In production. "
                "Google says External apps left in Testing issue refresh tokens that expire after 7 days.\n\n"
                "FACEBOOK\n"
                "1. Create an app at developers.facebook.com; add Facebook Login and configure "
                "Valid OAuth Redirect URI: http://localhost:8765/callback\n"
                "2. Add pages_show_list, pages_manage_posts, pages_read_engagement and business_management permissions.\n"
                "3. Enter the app ID, app secret and Business Portfolio ID above, then click Connect & Load Business Pages.\n"
                "4. Sign in and approve access. The app retrieves Page tokens from the Business Portfolio owned_pages endpoint.\n"
                "5. Select the Pages you want to publish to. Tokens are stored locally in your Windows user profile."
            ),
            justify="left",
            wraplength=850
        ).pack(anchor="w")

        footer = ttk.Frame(tab)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Button(footer, text="Open Google Cloud Console", command=lambda: webbrowser.open("https://console.cloud.google.com/")).pack(side="left")
        ttk.Button(footer, text="Open Meta Developers", command=lambda: webbrowser.open("https://developers.facebook.com/apps/")).pack(side="left", padx=6)
        ttk.Button(footer, text="Open Meta Graph API Explorer", command=lambda: webbrowser.open("https://developers.facebook.com/tools/explorer/")).pack(side="left")

    def _scroll_connections(self, event):
        try:
            if self.notebook.select() == str(self.connections_tab):
                units = int(-event.delta / 120)
                if units == 0 and event.delta:
                    units = -1 if event.delta > 0 else 1
                self.connections_canvas.yview_scroll(units, "units")
        except (AttributeError, tk.TclError):
            pass

    def build_logs_tab(self):
        tab = self.logs_tab
        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Label(top, text="Upload and scheduling activity", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="Clear view", command=self.clear_log_view).pack(side="right")
        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text = tk.Text(
            frame, wrap="word", state="disabled", font=("Cascadia Code", 9),
            background=self.colors["surface"], foreground=self.colors["text"],
            insertbackground=self.colors["accent"], relief="flat",
            highlightthickness=1, highlightbackground=self.colors["border"],
            padx=10, pady=8
        )
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=yscroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        ttk.Label(
            tab,
            text=f"Local logs: {LOG_PATH}",
            foreground="#777"
        ).pack(anchor="w", pady=(6, 0))

    def save_settings(self):
        self.settings.update({
            "folder": self.folder_var.get().strip(),
            "page_id": self.page_id_var.get().strip(),
            "business_id": self.business_id_var.get().strip(),
            "fb_selected_page_ids": [
                page_id for page_id, var in self.fb_page_vars.items() if var.get()
            ] if getattr(self, "fb_page_vars", None) else self.settings.get("fb_selected_page_ids", []),
            "client_secrets": self.client_secrets_var.get().strip(),
            "meta_app_id": self.meta_app_id_var.get().strip(),
            "meta_app_secret": self.meta_app_secret_var.get().strip(),
            "interval": int(self.interval_var.get() or 5),
            "youtube_enabled": self.youtube_var.get(),
            "facebook_enabled": self.facebook_var.get(),
            "youtube_ai": self.youtube_ai_var.get(),
            "facebook_ai": self.facebook_ai_var.get(),
            "category_id": self.category_var.get().split(" - ")[0].strip(),
            "made_for_kids": self.made_for_kids_var.get(),
            "start_at": self.start_var.get().strip(),
        })
        write_json(SETTINGS_PATH, self.settings)

    def refresh_page_selector(self):
        if not hasattr(self, "fb_page_checks"):
            return
        for child in self.fb_page_checks.winfo_children():
            child.destroy()
        self.fb_page_vars = {}
        pages = self.secrets.get("fb_pages") or []
        selected_ids = set(self.settings.get("fb_selected_page_ids") or [])
        if not pages:
            ttk.Label(self.fb_page_checks, text="No business Pages loaded yet.").pack(anchor="w")
            return
        for index, page in enumerate(pages):
            page_id = str(page.get("id", ""))
            page_name = page.get("name") or page_id
            var = tk.BooleanVar(value=page_id in selected_ids)
            self.fb_page_vars[page_id] = var
            ttk.Checkbutton(
                self.fb_page_checks,
                text=f"{page_name}  ({page_id})",
                variable=var,
                command=self.save_selected_pages
            ).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 20), pady=2)

    def save_selected_pages(self):
        self.settings["fb_selected_page_ids"] = [
            page_id for page_id, var in self.fb_page_vars.items() if var.get()
        ]
        self.save_settings()
        pages = self.get_selected_fb_pages()
        if self.secrets.get("fb_pages"):
            self.fb_status_label.configure(
                text=f"Loaded {len(self.secrets['fb_pages'])} Pages — {len(pages)} selected."
            )

    def get_selected_fb_pages(self):
        selected_ids = {
            page_id for page_id, var in self.fb_page_vars.items() if var.get()
        } if self.fb_page_vars else set(self.settings.get("fb_selected_page_ids") or [])
        return [
            dict(page) for page in (self.secrets.get("fb_pages") or [])
            if str(page.get("id")) in selected_ids and page.get("access_token")
        ]

    def get_fb_job(self, path, page_id):
        with self.db_lock:
            row = self.conn.execute(
                "SELECT * FROM facebook_page_jobs WHERE path=? AND page_id=?",
                (path, str(page_id))
            ).fetchone()
            return dict(row) if row else None

    def export_cleanup_report(self, show_dialog=True, selected_page_ids=None, include_youtube=None, include_facebook=None):
        import csv
        from datetime import datetime

        folder = Path(self.folder_var.get().strip())
        if not folder.is_dir():
            messagebox.showerror("Cleanup report", "The clip source folder does not exist.")
            return
        if selected_page_ids is None:
            selected_pages = self.get_selected_fb_pages()
            selected_page_ids = [p["id"] for p in selected_pages]
        else:
            selected_ids = {str(value) for value in selected_page_ids}
            selected_pages = [
                page for page in (self.secrets.get("fb_pages") or [])
                if str(page.get("id")) in selected_ids
            ]
        if include_youtube is None:
            include_youtube = bool(self.youtube_var.get())
        if include_facebook is None:
            include_facebook = bool(self.facebook_var.get())

        rows = self.get_clips()
        with self.db_lock:
            job_rows = self.conn.execute("SELECT * FROM facebook_page_jobs").fetchall()
        page_job_map = {
            (job["path"], str(job["page_id"])): dict(job)
            for job in job_rows
        }

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = folder / f"ScarClipScheduler_cleanup_report_{stamp}.csv"
        txt_path = folder / f"ScarClipScheduler_cleanup_report_{stamp}.txt"
        page_columns = [
            f"Facebook - {page.get('name') or page['id']} ({page['id']})"
            for page in selected_pages
        ]
        headers = [
            "MP4 file path", "TXT metadata path", "MP4 exists", "TXT exists",
            "YouTube status", *page_columns,
            "All selected uploads accepted",
            "All selected destinations published",
            "Deletion checklist note",
        ]
        text_lines = [
            "ScarClipScheduler local-file cleanup report",
            f"Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"Source folder: {folder}",
            "",
            "Scheduled means the platform accepted a future post; it does NOT mean public.",
            "Published means the platform API confirmed public publication.",
            "Only 'All selected destinations published = YES' is the delete-review signal.",
            "The app never deletes local files. Check the live posts before manually deleting.",
            "",
        ]

        csv_data = []
        accepted_count = 0
        published_count = 0
        for row in rows:
            mp4_path = Path(row["path"])
            txt_path_item = mp4_path.with_suffix(".txt")
            mp4_exists = mp4_path.is_file()
            txt_exists = txt_path_item.is_file()
            yt_status = row.get("yt_status") or "Pending"
            fb_statuses = []
            for page in selected_pages:
                job = page_job_map.get((row["path"], str(page["id"])))
                fb_statuses.append(job["status"] if job else "Not scheduled")

            selected_statuses = []
            if include_youtube:
                selected_statuses.append(str(yt_status))
            if include_facebook:
                if selected_pages:
                    selected_statuses.extend(str(status) for status in fb_statuses)
                else:
                    # Facebook was requested but no concrete Page was selected;
                    # never declare this row fully published from YouTube alone.
                    selected_statuses.append("No Facebook Page selected")

            accepted_states = {"scheduled", "published"}
            accepted_ok = bool(selected_statuses) and all(
                status.strip().lower() in accepted_states for status in selected_statuses
            )
            published_ok = bool(selected_statuses) and all(
                status.strip().lower() == "published" for status in selected_statuses
            )
            accepted_count += int(accepted_ok)
            published_count += int(published_ok)

            if published_ok:
                note = "Every selected destination is API-verified as published. Review the live posts before manually deleting local copies."
            elif accepted_ok:
                note = "NOT READY TO DELETE: all destinations accepted their schedules, but at least one scheduled post is not yet verified as published."
            else:
                note = "DO NOT DELETE: at least one selected destination is pending, failed, skipped, or not verified."

            record = [
                str(mp4_path), str(txt_path_item),
                "YES" if mp4_exists else "NO",
                "YES" if txt_exists else "NO",
                yt_status if include_youtube else "Not selected",
                *(fb_statuses[i] if include_facebook else "Not selected"
                  for i in range(len(selected_pages))),
                "YES" if accepted_ok else "NO",
                "YES" if published_ok else "NO",
                note,
            ]
            csv_data.append(record)
            text_lines.extend([
                f"MP4: {mp4_path}",
                f"TXT: {txt_path_item}",
                f"MP4 exists: {'YES' if mp4_exists else 'NO'} | TXT exists: {'YES' if txt_exists else 'NO'}",
                f"YouTube: {yt_status if include_youtube else 'Not selected'}",
            ])
            for index, page in enumerate(selected_pages):
                text_lines.append(
                    f"Facebook / {page.get('name') or page['id']}: "
                    f"{fb_statuses[index] if include_facebook else 'Not selected'}"
                )
            text_lines.append(f"All selected uploads accepted: {'YES' if accepted_ok else 'NO'}")
            text_lines.append(f"All selected destinations published: {'YES' if published_ok else 'NO'}")
            text_lines.append(f"Note: {note}")
            text_lines.append("-" * 80)

        with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(headers)
            writer.writerows(csv_data)
        txt_path.write_text("\n".join(text_lines), encoding="utf-8")
        self.log(f"Cleanup report exported: {csv_path}")
        if show_dialog:
            messagebox.showinfo(
                "Cleanup report created",
                f"Report files created:\n\nCSV:\n{csv_path}\n\nText:\n{txt_path}\n\n"
                f"{accepted_count} of {len(rows)} clip(s) have accepted/scheduled destinations.\n"
                f"{published_count} of {len(rows)} clip(s) are verified Published on every selected destination.\n"
                "No files were deleted."
            )
        return str(csv_path), str(txt_path)

    def ensure_output_folders(self):
        """Create upload, schedule, and API-publication-confirmed cleanup folders."""
        source_folder = Path(self.folder_var.get().strip())
        if not source_folder.is_dir():
            raise RuntimeError(f"Clip source folder does not exist: {source_folder}")
        for folder_name in ("uploaded", "schedule", "You can delete these clips now"):
            (source_folder / folder_name).mkdir(parents=True, exist_ok=True)
        safe_note = source_folder / "You can delete these clips now" / "READ ME FIRST.txt"
        if not safe_note.exists():
            safe_note.write_text(
                "The completed scheduled queue is moved here only after publication is verified across every recorded YouTube and Facebook Page destination.\\n"
                "This is a manual review folder. The app does NOT delete files automatically.\\n"
                "Check the public posts and keep any files you still need before manually deleting them.\\n",
                encoding="utf-8"
            )

    def move_clip_files(self, old_path, folder_name):
        """Move an MP4 and its matching TXT together, then update every local DB path."""
        source_video = Path(old_path)
        source_txt = source_video.with_suffix(".txt")
        source_folder = Path(self.folder_var.get().strip())
        target_folder = source_folder if folder_name == "__source__" else source_folder / folder_name

        if not source_video.is_file():
            self.log(f"File sorting skipped; MP4 not found: {source_video}")
            return None

        target_folder.mkdir(parents=True, exist_ok=True)
        if source_video.parent.resolve() == target_folder.resolve():
            return str(source_video)

        # Avoid overwriting an existing video, TXT, or queue record.
        candidate = target_folder / source_video.name
        suffix = 1
        while True:
            candidate_txt = candidate.with_suffix(".txt")
            with self.db_lock:
                db_collision = self.conn.execute(
                    "SELECT 1 FROM clips WHERE path=?", (str(candidate),)
                ).fetchone()
                job_collision = self.conn.execute(
                    "SELECT 1 FROM facebook_page_jobs WHERE path=? LIMIT 1", (str(candidate),)
                ).fetchone()
            if not candidate.exists() and not candidate_txt.exists() and not db_collision and not job_collision:
                break
            suffix += 1
            candidate = target_folder / f"{source_video.stem}_{suffix}{source_video.suffix}"

        target_txt = candidate.with_suffix(".txt")
        moved_video = False
        moved_txt = False
        try:
            shutil.move(str(source_video), str(candidate))
            moved_video = True
            if source_txt.is_file():
                shutil.move(str(source_txt), str(target_txt))
                moved_txt = True

            with self.db_lock:
                self.conn.execute("BEGIN IMMEDIATE")
                self.conn.execute(
                    "UPDATE facebook_page_jobs SET path=? WHERE path=?",
                    (str(candidate), str(source_video))
                )
                cur = self.conn.execute(
                    "UPDATE clips SET path=? WHERE path=?",
                    (str(candidate), str(source_video))
                )
                if cur.rowcount != 1:
                    raise RuntimeError("The clip's queue record could not be updated.")
                self.conn.commit()
        except Exception:
            with self.db_lock:
                self.conn.rollback()
            # Restore the original files if the database update failed.
            try:
                if moved_txt and target_txt.exists() and not source_txt.exists():
                    shutil.move(str(target_txt), str(source_txt))
                if moved_video and candidate.exists() and not source_video.exists():
                    shutil.move(str(candidate), str(source_video))
            except Exception as rollback_error:
                logger.exception("File-move rollback failed: %s", rollback_error)
            raise

        if self.selected_path == str(source_video):
            self.selected_path = str(candidate)
        self.txt_preview_cache.pop(str(source_txt), None)
        destination_label = "source folder" if folder_name == "__source__" else folder_name
        moved = f"{source_video.name} → {destination_label}"
        self.log(f"Automatically sorted: {moved}" + (" (matching TXT moved too)." if moved_txt else "."))
        return str(candidate)

    def organize_clip_after_upload(self, path, yt_enabled=None, fb_enabled=None, selected_pages=None):
        """Move only by verified state; the delete-safe folder requires publication everywhere."""
        with self.db_lock:
            row = self.conn.execute(
                "SELECT yt_status, yt_video_id FROM clips WHERE path=?", (str(path),)
            ).fetchone()
            jobs = self.conn.execute(
                "SELECT status FROM facebook_page_jobs WHERE path=?", (str(path),)
            ).fetchall()
        if not row:
            return False

        statuses = []
        yt_status = str(row["yt_status"] or "Pending").strip().lower()
        if row["yt_video_id"] or yt_status not in {"", "pending"}:
            statuses.append(yt_status)
        statuses.extend(str(job["status"] or "Pending").strip().lower() for job in jobs)

        if not statuses:
            return False

        published_states = {"published"}
        scheduled_states = {"scheduled"}
        uploaded_states = {"uploaded"}
        if all(status in (published_states | scheduled_states) for status in statuses):
            # Even an individually published clip stays in schedule until the
            # entire queued timeline is verified complete by the batch finalizer.
            destination = "schedule"
        elif all(status in uploaded_states for status in statuses):
            destination = "uploaded"
        else:
            # Pending, failed, skipped, unknown, or partially completed clips
            # belong back in the source folder, never in a success/safe folder.
            destination = "__source__"

        try:
            return bool(self.move_clip_files(path, destination))
        except Exception as exc:
            self.log(f"Automatic file sorting failed for {Path(path).name}: {exc}")
            logger.exception("Automatic file sorting failed for %s", path)
            return False

    def all_recorded_destinations_published(self):
        """Return True only when every YouTube/Page destination recorded in this queue is public."""
        with self.db_lock:
            clip_rows = self.conn.execute(
                "SELECT path, yt_status, yt_video_id, publish_at FROM clips"
            ).fetchall()
            page_rows = self.conn.execute(
                "SELECT path, page_id, status FROM facebook_page_jobs"
            ).fetchall()

        planned_destinations = 0
        for row in clip_rows:
            has_youtube_target = bool(
                row["yt_video_id"] or row["publish_at"] or
                str(row["yt_status"] or "Pending") not in {"", "Pending"}
            )
            if has_youtube_target:
                planned_destinations += 1
                if str(row["yt_status"] or "").lower() != "published":
                    return False

        for job in page_rows:
            planned_destinations += 1
            if str(job["status"] or "").lower() != "published":
                return False

        return planned_destinations > 0

    def move_completed_queue_to_safe_folder(self):
        """Move the whole scheduled batch only after every recorded destination is published."""
        if not self.all_recorded_destinations_published():
            return 0
        moved_count = 0
        for row in self.get_clips():
            with self.db_lock:
                page_jobs = self.conn.execute(
                    "SELECT status FROM facebook_page_jobs WHERE path=?",
                    (row["path"],)
                ).fetchall()
            statuses = []
            has_youtube_target = bool(
                row.get("yt_video_id") or row.get("publish_at") or
                str(row.get("yt_status") or "Pending") not in {"", "Pending"}
            )
            if has_youtube_target:
                statuses.append(str(row.get("yt_status") or "").lower())
            statuses.extend(str(job["status"] or "").lower() for job in page_jobs)
            if statuses and all(status == "published" for status in statuses):
                try:
                    if self.move_clip_files(row["path"], "You can delete these clips now"):
                        moved_count += 1
                except Exception as exc:
                    self.log(f"Could not move verified clip {Path(row['path']).name} to the final review folder: {exc}")
        self.log(
            f"All recorded scheduled destinations are verified Published. "
            f"Moved {moved_count} clip(s) into 'You can delete these clips now'."
        )
        return moved_count

    def check_publication_status(self, show_dialog=True):
        """Manually request a background check of all scheduled posts that are now due."""
        if self.verification_worker and self.verification_worker.is_alive():
            self.log("A publication-status check is already running.")
            return
        self.verification_button.configure(state="disabled")
        self.verification_worker = threading.Thread(
            target=self._publication_status_worker,
            args=(show_dialog,),
            daemon=True
        )
        self.verification_worker.start()

    def auto_check_publication_status(self):
        if self.root.winfo_exists():
            self.check_publication_status(show_dialog=False)
            self.root.after(15 * 60 * 1000, self.auto_check_publication_status)

    def _publication_status_worker(self, show_dialog):
        checked = 0
        newly_published = 0
        errors = []
        due_before = local_now() - timedelta(minutes=5)
        try:
            rows = self.get_clips()
            due_youtube = []
            for row in rows:
                if row.get("yt_status") != "Scheduled" or not row.get("yt_video_id"):
                    continue
                try:
                    publish_at = datetime.fromisoformat(row["publish_at"]).astimezone()
                except Exception:
                    continue
                if publish_at <= due_before:
                    due_youtube.append(row)

            if due_youtube:
                try:
                    from googleapiclient.discovery import build
                    creds = self.load_youtube_credentials(interactive=False)
                    if not creds:
                        raise RuntimeError("YouTube authorization is unavailable; reconnect to verify scheduled posts.")
                    service = build("youtube", "v3", credentials=creds, cache_discovery=False)
                    # videos.list accepts up to 50 IDs per request.
                    for offset in range(0, len(due_youtube), 50):
                        batch = due_youtube[offset:offset + 50]
                        ids = [r["yt_video_id"] for r in batch]
                        response = service.videos().list(part="status", id=",".join(ids)).execute()
                        by_id = {item.get("id"): item.get("status", {}) for item in response.get("items", [])}
                        for row in batch:
                            checked += 1
                            status = by_id.get(row["yt_video_id"])
                            if not status:
                                continue
                            privacy = str(status.get("privacyStatus") or "").lower()
                            upload_state = str(status.get("uploadStatus") or "").lower()
                            if privacy == "public" and upload_state == "processed":
                                self.db_execute(
                                    "UPDATE clips SET yt_status='Published', yt_error=NULL WHERE path=?",
                                    (row["path"],)
                                )
                                newly_published += 1
                                self.log(f"YouTube publication verified: {Path(row['path']).name}")
                            elif upload_state in {"failed", "rejected", "deleted"}:
                                reason = status.get("failureReason") or status.get("rejectionReason") or upload_state
                                self.db_execute(
                                    "UPDATE clips SET yt_status='Error', yt_error=? WHERE path=?",
                                    (f"YouTube status check: {reason}", row["path"])
                                )
                                errors.append(f"YouTube: {Path(row['path']).name} ({reason})")
                except Exception as exc:
                    errors.append(f"YouTube status check: {exc}")
                    self.log(f"YouTube publication verification could not complete: {exc}")

            with self.db_lock:
                due_jobs = self.conn.execute(
                    "SELECT * FROM facebook_page_jobs WHERE status='Scheduled'"
                ).fetchall()
            due_jobs = [dict(job) for job in due_jobs if self._is_publication_due(job["publish_at"], due_before)]
            page_tokens = {
                str(page.get("id")): page.get("access_token")
                for page in (self.secrets.get("fb_pages") or [])
                if page.get("id") and page.get("access_token")
            }
            legacy_id = str(self.secrets.get("fb_page_id") or "")
            legacy_token = self.secrets.get("fb_page_access_token")
            changed_fb_paths = set()
            for job in due_jobs:
                page_id = str(job["page_id"])
                if not job.get("video_id"):
                    errors.append(f"Facebook: no Reel video ID recorded for {job.get('page_name') or page_id}")
                    continue
                token = page_tokens.get(page_id)
                if not token and page_id == legacy_id:
                    token = legacy_token
                if not token:
                    errors.append(f"Facebook: missing Page token for {job.get('page_name') or page_id}")
                    continue
                try:
                    response = requests.get(
                        f"{GRAPH_BASE}/{job['video_id']}",
                        params={"fields": "status", "access_token": token},
                        timeout=30
                    )
                    self.raise_graph_error(response)
                    data = response.json()
                    status = data.get("status") or {}
                    publishing = status.get("publishing_phase") or {}
                    publish_status = str(publishing.get("publish_status") or "").lower()
                    phase_status = str(publishing.get("status") or "").lower()
                    video_status = str(status.get("video_status") or "").lower()
                    checked += 1
                    if publish_status == "published" and phase_status == "complete":
                        self.db_execute(
                            "UPDATE facebook_page_jobs SET status='Published', error=NULL WHERE path=? AND page_id=?",
                            (job["path"], page_id)
                        )
                        changed_fb_paths.add(job["path"])
                        newly_published += 1
                        self.log(
                            f"Facebook publication verified on {job.get('page_name') or page_id}: "
                            f"{Path(job['path']).name}"
                        )
                    elif publish_status == "error" or phase_status == "error" or video_status in {
                        "error", "upload_failed", "expired"
                    }:
                        detail = json.dumps(status, ensure_ascii=False)[:1200]
                        self.db_execute(
                            "UPDATE facebook_page_jobs SET status='Error', error=? WHERE path=? AND page_id=?",
                            (f"Facebook publication status: {detail}", job["path"], page_id)
                        )
                        changed_fb_paths.add(job["path"])
                        errors.append(f"Facebook: {Path(job['path']).name} on {job.get('page_name') or page_id} failed")
                except Exception as exc:
                    errors.append(f"Facebook status check for {job.get('page_name') or page_id}: {exc}")

            for path in changed_fb_paths:
                with self.db_lock:
                    page_rows = self.conn.execute(
                        "SELECT page_id FROM facebook_page_jobs WHERE path=?", (path,)
                    ).fetchall()
                pages = [{"id": str(r["page_id"])} for r in page_rows]
                self.update_fb_aggregate(path, pages)

            # Re-check every queue item, including ones whose scheduled time passed
            # while the app was closed. The organizer reads all recorded destinations.
            for row in self.get_clips():
                self.organize_clip_after_upload(row["path"])
            self.move_completed_queue_to_safe_folder()

            self.log(
                f"Publication check complete: {checked} destination status(es) checked, "
                f"{newly_published} newly confirmed published."
            )
            if errors:
                for error in errors[:10]:
                    self.log(f"Verification note: {error}")
            self.root.after(0, self.refresh_table)
            if show_dialog:
                summary = (
                    f"Checked {checked} destination status(es).\n"
                    f"Newly verified as published: {newly_published}.\n\n"
                    "Only clips confirmed Published on every recorded destination are moved to "
                    "'You can delete these clips now'."
                )
                if errors:
                    summary += f"\n\n{len(errors)} item(s) could not be verified or reported an error. They were not marked safe to delete."
                self.root.after(0, lambda m=summary: messagebox.showinfo("Publication status check", m))
        except Exception as exc:
            logger.exception("Publication status check failed: %s", exc)
            self.log(f"Publication status check failed: {exc}")
        finally:
            self.root.after(0, lambda: self.verification_button.configure(state="normal"))

    @staticmethod
    def _is_publication_due(value, due_before):
        try:
            return datetime.fromisoformat(value).astimezone() <= due_before
        except Exception:
            return False

    def browse_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.folder_var.get() or str(Path.home()))
        if chosen:
            self.folder_var.set(chosen)
            self.save_settings()

    def browse_client_secrets(self):
        chosen = filedialog.askopenfilename(
            title="Select Google OAuth Desktop client JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if chosen:
            self.client_secrets_var.set(chosen)
            self.save_settings()

    def log(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        logger.info(message)
        def append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(0, append)

    def clear_log_view(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def db_execute(self, sql, params=()):
        with self.db_lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def get_clips(self):
        with self.db_lock:
            return [dict(row) for row in self.conn.execute("SELECT * FROM clips ORDER BY path").fetchall()]

    def get_txt_preview(self, video_path):
        """Read the matching same-basename TXT file and return a compact, cached preview."""
        txt_path = Path(video_path).with_suffix(".txt")
        if not txt_path.is_file():
            return "[MISSING MATCHING TXT]"
        try:
            stat = txt_path.stat()
            cache_key = str(txt_path)
            cached = self.txt_preview_cache.get(cache_key)
            signature = (stat.st_mtime_ns, stat.st_size)
            if cached and cached[0] == signature:
                return cached[1]
            raw = txt_path.read_text(encoding="utf-8-sig", errors="replace")
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            preview = " | ".join(lines[:2]) if lines else "[EMPTY TXT FILE]"
            if len(preview) > 105:
                preview = preview[:102].rstrip() + "..."
            self.txt_preview_cache[cache_key] = (signature, preview)
            return preview
        except Exception as exc:
            logger.warning("Unable to read matching TXT %s: %s", txt_path, exc)
            return "[UNREADABLE TXT]"

    def get_selected_clip_paths(self):
        """Return full paths for the selected rows, avoiding ambiguous same-name files."""
        mapping = getattr(self, "tree_path_by_id", {})
        return [mapping[item] for item in self.tree.selection() if item in mapping]

    @staticmethod
    def filter_queue_rows(rows, selected_paths=None):
        """Use selected paths when supplied; an empty selection preserves whole-queue behaviour."""
        selected = {str(path) for path in (selected_paths or [])}
        if not selected:
            return list(rows)
        return [row for row in rows if str(row.get("path")) in selected]

    def select_all_clips(self):
        items = self.tree.get_children()
        if items:
            self.tree.selection_set(items)
        self.update_clip_selection_count()

    def unselect_all_clips(self):
        self.tree.selection_remove(self.tree.selection())
        self.update_clip_selection_count()

    def update_clip_selection_count(self, _event=None):
        if hasattr(self, "clip_selection_var") and hasattr(self, "tree"):
            self.clip_selection_var.set(clip_selection_summary(len(self.tree.selection())))

    def delete_selected_from_list(self):
        """Remove selected records from the local queue without touching source MP4/TXT files."""
        paths = self.get_selected_clip_paths()
        if not paths:
            messagebox.showinfo("Select videos", "Select one or more videos in the list first.")
            return
        active = (
            getattr(self, "worker", None),
            getattr(self, "scan_worker", None),
            getattr(self, "verification_worker", None),
        )
        if any(worker and worker.is_alive() for worker in active):
            messagebox.showwarning(
                "Queue is busy",
                "Wait for scanning, scheduling, or publication verification to finish before removing queue entries."
            )
            return

        # Chunk large selections to stay below SQLite's host-parameter limit.
        scheduled = 0
        scheduled_pages = 0
        with self.db_lock:
            for offset in range(0, len(paths), 500):
                batch = paths[offset:offset + 500]
                placeholders = ",".join("?" for _ in batch)
                scheduled += self.conn.execute(
                    f"SELECT COUNT(*) FROM clips WHERE path IN ({placeholders}) "
                    "AND (yt_status IN ('Scheduled','Published') OR yt_video_id IS NOT NULL)",
                    tuple(batch)
                ).fetchone()[0]
                scheduled_pages += self.conn.execute(
                    f"SELECT COUNT(*) FROM facebook_page_jobs WHERE path IN ({placeholders}) "
                    "AND (status IN ('Scheduled','Published') OR video_id IS NOT NULL)",
                    tuple(batch)
                ).fetchone()[0]

        warning = (
            f"Remove {len(paths)} selected video(s) from the local queue?\n\n"
            "This removes only their queue records and per-Page status history. "
            "The MP4 and TXT files will stay on disk. Any post already accepted by YouTube or Facebook "
            "will remain scheduled/published on that platform; this action does not cancel it.\n\n"
            f"Local records with accepted YouTube destinations: {scheduled}\n"
            f"Local Facebook Page jobs with accepted destinations: {scheduled_pages}\n\n"
            "Continue?"
        )
        if not messagebox.askyesno("Delete selected queue entries", warning):
            return

        removed = 0
        try:
            with self.db_lock:
                self.conn.execute("BEGIN IMMEDIATE")
                for path in paths:
                    self.conn.execute("DELETE FROM facebook_page_jobs WHERE path=?", (path,))
                    cur = self.conn.execute("DELETE FROM clips WHERE path=?", (path,))
                    removed += cur.rowcount
                self.conn.commit()
        except Exception:
            with self.db_lock:
                self.conn.rollback()
            raise

        if self.selected_path in paths:
            self.selected_path = None
            self.selection_title_var.set("")
            self.selection_desc.delete("1.0", "end")
        for path in paths:
            self.txt_preview_cache.pop(str(Path(path).with_suffix(".txt")), None)
        self.log(
            f"Removed {removed} video(s) from the local queue. Source MP4/TXT files were kept on disk."
        )
        self.refresh_table()

    @staticmethod
    def get_queue_row_status(row, page_job_map, selected_pages, include_youtube, include_facebook):
        statuses = []

        if include_youtube:
            statuses.append(str(row.get("yt_status") or "Pending").strip().lower())

        if include_facebook:
            if selected_pages:
                for page in selected_pages:
                    job = page_job_map.get((row["path"], str(page["id"])))
                    statuses.append(
                        str((job or {}).get("status") or "Pending").strip().lower()
                    )
            else:
                # Do not imply Facebook scheduling when no Page is selected.
                statuses.append("no page selected")

        if not statuses:
            return "Choose platform"

        if any(status == "error" or status.startswith("error") for status in statuses):
            return "⚠ Failed"
        if any(status.startswith("skipped") for status in statuses):
            return "⚠ Skipped"

        published_states = {"published"}
        scheduled_states = {"scheduled", "published"}
        if all(status in published_states for status in statuses):
            return "✓ Published"
        if all(status in scheduled_states for status in statuses) and any(
            status == "scheduled" for status in statuses
        ):
            return "✓ Scheduled"
        if all(status == "uploaded" for status in statuses):
            return "↑ Uploaded"
        if any(status in {"scheduled", "published", "uploaded"} for status in statuses):
            return "◐ Partial"
        return "Pending"

    @staticmethod
    def queue_row_sort_key(item):
        row, display_status = item
        rank = {
            "Pending": 0,
            "Choose platform": 0,
            "⚠ Failed": 1,
            "⚠ Skipped": 1,
            "◐ Partial": 2,
            "↑ Uploaded": 3,
            "✓ Scheduled": 4,
            "✓ Published": 5,
        }.get(display_status, 0)
        return (
            rank,
            str(row.get("publish_at") or "9999-12-31"),
            Path(row["path"]).name.lower(),
        )

    def refresh_table(self):
        try:
            if hasattr(self, "tree"):
                selected_paths = set(self.get_selected_clip_paths())
                for item in self.tree.get_children():
                    self.tree.delete(item)
                self.tree_path_by_id = {}

                rows = self.get_clips()
                include_youtube = bool(self.youtube_var.get())
                include_facebook = bool(self.facebook_var.get())
                selected_pages = self.get_selected_fb_pages() if include_facebook else []

                with self.db_lock:
                    job_rows = self.conn.execute(
                        "SELECT path, page_id, status FROM facebook_page_jobs"
                    ).fetchall()
                page_job_map = {
                    (job["path"], str(job["page_id"])): dict(job)
                    for job in job_rows
                }

                decorated = [
                    (
                        row,
                        self.get_queue_row_status(
                            row, page_job_map, selected_pages,
                            include_youtube, include_facebook
                        )
                    )
                    for row in rows
                ]
                decorated.sort(key=self.queue_row_sort_key)

                state_counts = {}
                for _row, state in decorated:
                    state_counts[state] = state_counts.get(state, 0) + 1
                scheduled_count = state_counts.get("✓ Scheduled", 0)
                published_count = state_counts.get("✓ Published", 0)
                pending_count = state_counts.get("Pending", 0) + state_counts.get("Choose platform", 0)
                failed_count = state_counts.get("⚠ Failed", 0) + state_counts.get("⚠ Skipped", 0)
                partial_count = state_counts.get("◐ Partial", 0)
                uploaded_count = state_counts.get("↑ Uploaded", 0)
                fb_good = sum(1 for row in rows if row["fb_ok"] == 1)

                self.queue_summary_var.set(
                    f"{len(rows)} clips  •  {pending_count} pending  •  "
                    f"{partial_count} partial  •  {scheduled_count} scheduled  •  "
                    f"{published_count} published  •  {uploaded_count} uploaded  •  "
                    f"{failed_count} failed/skipped  •  {fb_good}/{len(rows)} Facebook-format OK"
                )

                for index, (row, display_status) in enumerate(decorated):
                    duration = f"{row['duration']:.1f}s" if row.get("duration") else "—"
                    description_preview = " ".join(str(row.get("description") or "").split())
                    if len(description_preview) > 150:
                        description_preview = description_preview[:147].rstrip() + "..."
                    tags = []
                    if display_status in {"⚠ Failed", "⚠ Skipped"}:
                        tags.append("error")
                    elif display_status == "✓ Scheduled":
                        tags.append("scheduled")
                    elif display_status == "✓ Published":
                        tags.append("published")
                    elif display_status in {"◐ Partial", "↑ Uploaded"}:
                        tags.append("partial")
                    else:
                        tags.append("pending")

                    item_id = str(index)
                    self.tree.insert(
                        "", "end", iid=item_id,
                        values=(
                            index + 1,
                            display_status,
                            Path(row["path"]).name,
                            row["title"],
                            description_preview,
                            duration,
                            row["yt_status"],
                            row["fb_status"],
                            fmt_dt(row["publish_at"] or "")
                        ),
                        tags=tuple(tags)
                    )
                    self.tree_path_by_id[item_id] = row["path"]

                restored = [
                    item for item in self.tree.get_children()
                    if self.tree_path_by_id.get(item) in selected_paths
                ]
                if restored:
                    self.tree.selection_set(restored)
                self.update_clip_selection_count()
        except Exception as exc:
            logger.exception("Table refresh failed: %s", exc)
        self.root.after(2500, self.refresh_table)

    def scan_folder(self):
        folder = Path(self.folder_var.get().strip())
        if not folder.is_dir():
            messagebox.showerror("Folder not found", f"Cannot find folder:\n{folder}")
            return
        try:
            for folder_name in ("uploaded", "schedule", "You can delete these clips now"):
                (folder / folder_name).mkdir(parents=True, exist_ok=True)
            safe_note = folder / "You can delete these clips now" / "READ ME FIRST.txt"
            if not safe_note.exists():
                safe_note.write_text(
                    "The completed scheduled queue is moved here only after publication is verified across every recorded YouTube and Facebook Page destination.\\n"
                    "This is a manual review folder. The app does NOT delete files automatically.\\n"
                    "Check the platform posts and keep any files you still need before manually deleting them.\\n",
                    encoding="utf-8"
                )
        except Exception as exc:
            messagebox.showerror("Folder setup failed", str(exc))
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "Wait for the current upload/scheduling task to finish or stop it first.")
            return
        if self.scan_worker and self.scan_worker.is_alive():
            messagebox.showinfo("Scan running", "A folder scan is already in progress.")
            return
        self.save_settings()
        self.scan_worker = threading.Thread(target=self._scan_worker, args=(folder,), daemon=True)
        self.scan_worker.start()

    def _scan_worker(self, folder):
        try:
            videos = sorted(folder.glob("*.mp4"), key=lambda p: p.name.lower())
            if not videos:
                self.log("No MP4 files found in the selected folder.")
                return
            added = 0
            missing_txt = 0
            for i, video in enumerate(videos, start=1):
                txt = clip_sidecar_path(video)
                if txt.exists():
                    title, description = parse_txt(txt)
                else:
                    missing_txt += 1
                    title, description = video.stem, ""
                width, height, duration, fb_ok = probe_video(video)
                self.db_execute(
                    """INSERT OR IGNORE INTO clips
                    (path,title,description,width,height,duration,fb_ok,modified)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (str(video), title, description, width, height, duration,
                     1 if fb_ok else (0 if fb_ok is False else None), video.stat().st_mtime)
                )
                added += 1
                if i % 20 == 0:
                    self.log(f"Scanned {i}/{len(videos)} videos…")
            self.log(f"Scan complete: {len(videos)} MP4 files, {added} matched TXT pairs, {missing_txt} missing TXT files.")
            rows = self.get_clips()
            yt_pending = sum(1 for r in rows if r["yt_status"] not in {"Scheduled", "Published"})
            recommended = suggested_start(yt_pending, self.youtube_var.get())
            self.log(
                f"Suggested first-post time: {recommended.strftime('%Y-%m-%d %H:%M')} local time. "
                "Your chosen start time is unchanged; review it and press Confirm start time."
            )
            if ffprobe_path():
                bad = [r for r in rows if r["fb_ok"] == 0]
                self.log(f"Facebook Reel format check: {len(rows) - len(bad)}/{len(rows)} clips pass 9:16 and 4–60 second checks.")
                if bad:
                    self.log(f"{len(bad)} clips will be skipped on Facebook unless you fix their format.")
            else:
                self.log("ffprobe not found; Facebook Reel dimensions and duration could not be pre-checked.")
            self.root.after(0, self.refresh_table)
        except Exception as exc:
            self.log(f"Scan failed: {exc}")

    def on_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            self.selected_path = None
            self.selection_title_var.set("")
            self.selection_desc.delete("1.0", "end")
            return
        path = getattr(self, "tree_path_by_id", {}).get(selection[0])
        if not path:
            return
        row = next((r for r in self.get_clips() if r["path"] == path), None)
        if not row:
            return
        self.selected_path = row["path"]
        self.selection_title_var.set(row["title"])
        self.selection_desc.delete("1.0", "end")
        self.selection_desc.insert("1.0", row["description"])

    def focus_metadata_editor(self, _event=None):
        """Double-click a row to focus its title editor."""
        self.on_select()
        if self.selected_path:
            self.selection_title_entry.focus_set()
            self.selection_title_entry.selection_range(0, "end")

    def save_selected_metadata(self):
        if not self.selected_path:
            messagebox.showinfo("Select a clip", "Select a row in the queue first.")
            return
        title = self.selection_title_var.get().strip()
        desc = self.selection_desc.get("1.0", "end-1c").strip()
        if not title:
            messagebox.showerror("Title required", "Enter a video title.")
            return
        if len(title) > 100:
            messagebox.showerror("Title too long", "YouTube titles must be 100 characters or fewer.")
            return
        if len(desc.encode("utf-8")) > 5000:
            messagebox.showerror("Description too long", "YouTube descriptions must be 5,000 bytes or fewer.")
            return
        self.db_execute("UPDATE clips SET title=?, description=? WHERE path=?", (title, desc, self.selected_path))
        self.log(f"Saved metadata override for {Path(self.selected_path).name}")
        self.refresh_table()

    def set_recommended_start(self):
        rows = self.filter_queue_rows(self.get_clips(), self.get_selected_clip_paths())
        pending = [r for r in rows if r["yt_status"] not in {"Scheduled", "Published"}] if self.youtube_var.get() else [
            r for r in rows if r["fb_status"] not in {"Scheduled", "Published"}
        ]
        start = suggested_start(len(pending), self.youtube_var.get())
        self.start_var.set(start.strftime("%Y-%m-%d %H:%M"))
        self.save_settings()

    def load_youtube_credentials(self, interactive=False):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        creds = None
        if YT_TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(YT_TOKEN_PATH), YT_SCOPES)
            except Exception:
                creds = None
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            YT_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        if (not creds or not creds.valid) and interactive:
            from google_auth_oauthlib.flow import InstalledAppFlow
            client_path = self.client_secrets_var.get().strip()
            if not client_path or not Path(client_path).is_file():
                raise RuntimeError("Select your Google OAuth Desktop client JSON file first.")
            flow = InstalledAppFlow.from_client_secrets_file(client_path, YT_SCOPES)
            creds = flow.run_local_server(
                host="localhost", port=0, open_browser=True,
                access_type="offline", prompt="consent"
            )
            YT_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        if not creds or not creds.valid:
            return None
        return creds

    def connect_youtube(self):
        self.save_settings()
        def task():
            try:
                creds = self.load_youtube_credentials(interactive=True)
                from googleapiclient.discovery import build
                service = build("youtube", "v3", credentials=creds, cache_discovery=False)
                result = service.channels().list(part="snippet", mine=True).execute()
                items = result.get("items") or []
                if not items:
                    raise RuntimeError("No YouTube channel was returned for the Google account you authorized.")
                channel = items[0]
                self.secrets["yt_channel_title"] = channel["snippet"]["title"]
                self.secrets["yt_channel_id"] = channel["id"]
                write_json(CREDENTIALS_PATH, self.secrets)
                self.log(f"Connected YouTube channel: {channel['snippet']['title']} ({channel['id']})")
                self.root.after(0, self.refresh_connections)
                self.root.after(0, lambda: messagebox.showinfo("YouTube connected", f"Connected channel:\n{channel['snippet']['title']}"))
            except Exception as exc:
                self.log(f"YouTube connection failed: {exc}")
                self.root.after(0, lambda e=str(exc): messagebox.showerror("YouTube connection failed", e))
        threading.Thread(target=task, daemon=True).start()

    def connect_facebook(self):
        self.save_settings()
        app_id = self.meta_app_id_var.get().strip()
        app_secret = self.meta_app_secret_var.get().strip()
        business_id = self.business_id_var.get().strip()
        if not app_id or not app_secret or not business_id:
            messagebox.showerror(
                "Facebook setup incomplete",
                "Enter the Meta App ID, App Secret and ScarZero Business Portfolio ID."
            )
            return
        self.log("Starting Facebook Business Portfolio authorization in your browser…")
        threading.Thread(
            target=self._facebook_oauth_worker,
            args=(app_id, app_secret, business_id),
            daemon=True
        ).start()

    def _facebook_oauth_worker(self, app_id, app_secret, business_id):
        server = None
        try:
            state = secrets.token_urlsafe(24)
            redirect_uri = "http://localhost:8765/callback"
            server = HTTPServer(("localhost", 8765), FacebookCallbackHandler)
            server.oauth_result = None
            params = {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": "pages_show_list,pages_manage_posts,pages_read_engagement,business_management",
                "response_type": "code",
            }
            auth_url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?{urlencode(params)}"
            webbrowser.open(auth_url)
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline and not server.oauth_result:
                server.timeout = 1
                server.handle_request()
            result = server.oauth_result
            if not result:
                raise RuntimeError("Facebook authorization timed out. Check the Valid OAuth Redirect URI and try again.")
            if result.get("state") != state:
                raise RuntimeError("Facebook returned an invalid OAuth state.")
            if result.get("error"):
                raise RuntimeError(f"Facebook authorization was denied: {result['error']}")
            code = result.get("code")
            if not code:
                raise RuntimeError("Facebook did not return an authorization code.")

            token_response = requests.get(
                f"{GRAPH_BASE}/oauth/access_token",
                params={
                    "client_id": app_id,
                    "redirect_uri": redirect_uri,
                    "client_secret": app_secret,
                    "code": code,
                },
                timeout=30
            )
            token_response.raise_for_status()
            short_token = token_response.json()["access_token"]

            long_response = requests.get(
                f"{GRAPH_BASE}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": short_token,
                },
                timeout=30
            )
            self.raise_graph_error(long_response)
            user_token = long_response.json()["access_token"]

            pages_response = requests.get(
                f"{GRAPH_BASE}/{business_id}/owned_pages",
                params={
                    "fields": "id,name,access_token",
                    "limit": 100,
                    "access_token": user_token,
                },
                timeout=30
            )
            self.raise_graph_error(pages_response)
            raw_pages = pages_response.json().get("data", [])
            valid_pages = [
                {
                    "id": str(page.get("id")),
                    "name": page.get("name") or str(page.get("id")),
                    "access_token": page.get("access_token"),
                }
                for page in raw_pages
                if page.get("id") and page.get("access_token")
            ]
            if not valid_pages:
                raise RuntimeError(
                    "Meta authorized your account, but the ScarZero Business Portfolio returned no Pages with access tokens. "
                    "Check the Business Portfolio ID and business_management permission."
                )
            missing = [
                f"{page.get('name')} ({page.get('id')})"
                for page in raw_pages if page.get("id") and not page.get("access_token")
            ]
            self.secrets["fb_pages"] = valid_pages
            self.secrets["fb_business_id"] = str(business_id)
            # Retain compatibility with previous single-Page app settings.
            self.secrets["fb_page_id"] = valid_pages[0]["id"]
            self.secrets["fb_page_name"] = valid_pages[0]["name"]
            self.secrets["fb_page_access_token"] = valid_pages[0]["access_token"]
            write_json(CREDENTIALS_PATH, self.secrets)

            valid_ids = {page["id"] for page in valid_pages}
            selected = set(self.settings.get("fb_selected_page_ids") or [])
            self.settings["fb_selected_page_ids"] = sorted(selected & valid_ids) if selected else []
            self.settings["business_id"] = str(business_id)
            write_json(SETTINGS_PATH, self.settings)

            summary = f"Loaded {len(valid_pages)} Page(s) from ScarZero: " + ", ".join(p["name"] for p in valid_pages)
            if missing:
                summary += "\nNo access token returned for: " + ", ".join(missing)
            self.log(summary)
            self.root.after(0, self.refresh_connections)
            self.root.after(
                0,
                lambda n=len(valid_pages): messagebox.showinfo(
                    "Facebook Business connected",
                    f"Loaded {n} Page(s) from the ScarZero Business Portfolio.\n\n"
                    "Select the Pages you want in the Connections tab."
                )
            )
        except OSError as exc:
            message = str(exc)
            if "Address already in use" in message or "Only one usage" in message:
                message = "Port 8765 is already in use. Close the app/process using it and reconnect."
            self.log(f"Facebook connection failed: {message}")
            self.root.after(0, lambda e=message: messagebox.showerror("Facebook connection failed", e))
        except Exception as exc:
            self.log(f"Facebook connection failed: {exc}")
            self.root.after(0, lambda e=str(exc): messagebox.showerror("Facebook connection failed", e))
        finally:
            if server:
                server.server_close()

    def refresh_connections(self):
        yt_name = self.secrets.get("yt_channel_title") or ""
        if YT_TOKEN_PATH.exists() and yt_name:
            self.yt_status_label.configure(text=f"Connected: {yt_name}")
        elif YT_TOKEN_PATH.exists():
            self.yt_status_label.configure(text="YouTube token exists; reconnect if upload authorization fails.")
        else:
            self.yt_status_label.configure(text="Not connected — select OAuth Desktop JSON and connect.")
        pages = self.secrets.get("fb_pages") or []
        if pages:
            selected = set(self.settings.get("fb_selected_page_ids") or [])
            fb_status = f"Business connected: {len(pages)} Pages loaded — {len(selected)} selected."
            self.fb_status_label.configure(text=fb_status)
        elif self.secrets.get("fb_page_access_token"):
            fb_status = "Legacy Page token found — reconnect to load Business Portfolio Pages."
            self.fb_status_label.configure(text=fb_status)
        else:
            fb_status = "Not connected — enter Meta App details and connect."
            self.fb_status_label.configure(text=fb_status)
        self.refresh_page_selector()
        self.connection_status_var.set(
            f"YouTube: {yt_name or 'not connected'}  |  Facebook: {fb_status}"
        )

    def reset_failed(self):
        self.db_execute(
            "UPDATE clips SET yt_status='Pending', yt_error=NULL WHERE yt_status LIKE 'Error%'"
        )
        self.db_execute(
            "UPDATE clips SET fb_status='Pending', fb_error=NULL WHERE fb_status LIKE 'Error%'"
        )
        self.db_execute(
            "UPDATE facebook_page_jobs SET status='Pending', error=NULL WHERE status='Error'"
        )
        self.log("Failed items reset to Pending. Successful Page schedules were left unchanged.")
        self.refresh_table()

    def start_scheduling(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Already running", "A scheduling process is already running.")
            return
        all_rows = self.get_clips()
        selected_paths = self.get_selected_clip_paths()
        rows = self.filter_queue_rows(all_rows, selected_paths)
        if not rows:
            messagebox.showwarning("Queue empty", "Scan the clip folder first.")
            return
        yt_enabled = self.youtube_var.get()
        fb_enabled = self.facebook_var.get()
        selected_pages = self.get_selected_fb_pages() if fb_enabled else []
        if not yt_enabled and not fb_enabled:
            messagebox.showerror("Choose a platform", "Select YouTube, Facebook, or both.")
            return
        if fb_enabled and not selected_pages:
            messagebox.showerror(
                "Select Facebook Pages",
                "Open Connections and select at least one Facebook Page from the ScarZero Business Portfolio."
            )
            return
        if not self.rights_confirm_var.get():
            messagebox.showwarning(
                "Confirm publishing rights",
                "Confirm that you own these videos or have permission to repost them, and that the content follows platform rules."
            )
            return
        if yt_enabled:
            try:
                if not self.load_youtube_credentials(interactive=False):
                    raise RuntimeError("YouTube is not connected. Open Connections and connect your channel.")
            except Exception as exc:
                messagebox.showerror("YouTube connection required", str(exc))
                return
        try:
            start = datetime.strptime(self.start_var.get().strip(), "%Y-%m-%d %H:%M").astimezone()
            interval = validate_interval_minutes(self.interval_var.get())
        except Exception as exc:
            messagebox.showerror("Invalid schedule", str(exc))
            return

        minimum_start = local_now() + timedelta(minutes=15)
        if start < minimum_start:
            raise ValueError(
                "The confirmed first-post time must be at least 15 minutes from now. "
                "Choose a later time and confirm it again."
            )

        # Respect the user's confirmed start time. YouTube quota pauses are
        # handled by the worker and deferred items are shifted to the next day.
        if yt_enabled:
            # A newly confirmed schedule replaces reservations for every unaccepted
            # clip, but already accepted YouTube posts retain their original times.
            allocation_rows = []
            for queue_row in rows:
                allocation_row = dict(queue_row)
                status = str(allocation_row.get("yt_status") or "Pending").strip().lower()
                if status not in {"scheduled", "published"}:
                    allocation_row["publish_at"] = None
                allocation_rows.append(allocation_row)
            youtube_slots = allocate_youtube_publish_slots(allocation_rows, start, interval)
            for path, slot in youtube_slots.items():
                self.db_execute(
                    "UPDATE clips SET publish_at=? WHERE path=?",
                    (slot, path)
                )

        # Meta's Reels publishing guide describes a limit of 30 API-published
        # Reels per Page in a moving 24-hour period. Leave a five-minute buffer.
        if fb_enabled:
            for page in selected_pages:
                page_id = str(page["id"])
                sequence = 0
                for row in rows:
                    job = self.get_fb_job(row["path"], page_id)
                    if job and str(job.get("status") or "Pending") in {"Scheduled", "Published"}:
                        continue
                    if job and str(job.get("status") or "").startswith("Skipped"):
                        continue
                    slot = start + timedelta(minutes=sequence * interval)
                    sequence += 1
                    if job:
                        self.db_execute(
                            """UPDATE facebook_page_jobs SET publish_at=?
                            WHERE path=? AND page_id=? AND status NOT IN ('Scheduled','Published')""",
                            (slot.astimezone().isoformat(), row["path"], page_id)
                        )
                    else:
                        self.db_execute(
                            """INSERT INTO facebook_page_jobs
                            (path,page_id,page_name,publish_at,status)
                            VALUES (?,?,?,?, 'Pending')""",
                            (row["path"], page_id, page.get("name") or page_id, slot.astimezone().isoformat())
                        )
                with self.db_lock:
                    latest = self.conn.execute(
                        "SELECT MAX(publish_at) FROM facebook_page_jobs WHERE page_id=?",
                        (page_id,)
                    ).fetchone()[0]
                if latest:
                    latest_dt = datetime.fromisoformat(latest).astimezone()
                    if latest_dt > local_now() + timedelta(days=28):
                        messagebox.showerror(
                            "Facebook scheduling window",
                            f"The planned queue for {page.get('name')} extends beyond 28 days. "
                            "Schedule fewer clips in this run."
                        )
                        return

        incompatible = [r for r in rows if fb_enabled and r["fb_ok"] == 0]
        if incompatible and not messagebox.askyesno(
            "Facebook format warning",
            f"{len(incompatible)} clip(s) failed the Facebook Reel 9:16 / 4–60 second pre-check.\n"
            "They will be skipped on Facebook but can still go to YouTube. Continue?"
        ):
            return

        pending_paths = []
        for row in rows:
            yt_todo = yt_enabled and row["yt_status"] not in {"Scheduled", "Published"}
            fb_todo = False
            if fb_enabled:
                for page in selected_pages:
                    job = self.get_fb_job(row["path"], page["id"])
                    if not job or job["status"] not in {"Scheduled", "Published"}:
                        fb_todo = True
                        break
            if yt_todo or fb_todo:
                pending_paths.append(row["path"])
        if not pending_paths:
            try:
                self.ensure_output_folders()
                for row in rows:
                    self.organize_clip_after_upload(row["path"], yt_enabled, fb_enabled, selected_pages)
            except Exception as exc:
                self.log(f"Could not create automatic sorting folders: {exc}")
            messagebox.showinfo("Queue complete", "All selected destinations have already accepted the scheduled uploads.")
            self.export_cleanup_report(show_dialog=False)
            self.check_publication_status(show_dialog=False)
            return

        page_names = ", ".join(page.get("name") or page["id"] for page in selected_pages)
        fb_message = (
            f"Facebook Pages: {page_names}\n"
            "Facebook limit: plan for at most 30 API Reels per Page per moving 24 hours; "
            "the next batch is delayed by 24 hours plus a 5-minute buffer.\n"
            if fb_enabled else ""
        )
        scope = (
            f"Selected videos: {len(rows)} clip(s)"
            if selected_paths else f"Entire queue: {len(rows)} clip(s)"
        )
        confirm = (
            f"Schedule {len(pending_paths)} pending clip(s)?\n"
            f"{scope}\n\n"
            f"First post: {start.strftime('%Y-%m-%d %H:%M')} local time\n"
            f"Interval: {interval} minutes\n"
            f"Platforms: {', '.join(x for x, ok in [('YouTube', yt_enabled), ('Facebook', fb_enabled)] if ok)}\n"
            f"{fb_message}\n"
            "The app uploads files now and asks each selected platform/Page to publish at the scheduled time. "
            "YouTube's default upload quota is 100 videos per Pacific quota day. "
            "Do not close the app while uploads are running."
        )
        if not messagebox.askyesno("Confirm scheduling", confirm):
            return

        try:
            self.ensure_output_folders()
        except Exception as exc:
            messagebox.showerror("File sorting folders unavailable", str(exc))
            return
        self.save_settings()
        self.stop_event.clear()
        self.schedule_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.worker = threading.Thread(
            target=self._schedule_worker,
            args=(
                yt_enabled, fb_enabled, self.youtube_ai_var.get(), self.facebook_ai_var.get(),
                self.made_for_kids_var.get(), self.category_var.get().split(" - ")[0].strip(),
                selected_pages, tuple(pending_paths),
            ),
            daemon=True
        )
        self.worker.start()

    def stop_scheduling(self):
        if not self.worker or not self.worker.is_alive():
            self.stop_button.configure(state="disabled", text="Stop queue")
            return
        self.stop_event.set()
        self.stop_button.configure(state="disabled", text="Stopping...")
        self.log(
            "Stop requested. The active platform upload will finish; remaining clips will stay pending. "
            "Uploads already accepted by YouTube or Facebook remain scheduled."
        )

    def _schedule_worker(
        self, yt_enabled, fb_enabled, yt_ai, fb_ai, made_for_kids,
        category_id, selected_pages, clip_paths=None
    ):
        try:
            rows = self.filter_queue_rows(self.get_clips(), clip_paths)
            self.log("Queue processing started.")
            for row_index, row in enumerate(rows):
                if self.stop_event.is_set():
                    break
                path = row["path"]
                name = Path(path).name
                title = row["title"]
                description = row["description"]

                if yt_enabled and row["yt_status"] not in {"Scheduled", "Published"}:
                    if not row.get("publish_at"):
                        self.db_execute(
                            "UPDATE clips SET yt_status='Error', yt_error=? WHERE path=?",
                            ("No YouTube publish time has been assigned.", path)
                        )
                    else:
                        publish_at = datetime.fromisoformat(row["publish_at"]).astimezone()
                        while not self.stop_event.is_set():
                            try:
                                self.log(f"YouTube upload: {name}")
                                video_id = self.upload_youtube(
                                    path, title, description, publish_at,
                                    yt_ai, made_for_kids, category_id
                                )
                                self.db_execute(
                                    "UPDATE clips SET yt_status='Scheduled', yt_video_id=?, yt_error=NULL WHERE path=?",
                                    (video_id, path)
                                )
                                self.log(f"YouTube accepted: {name} → {publish_at.strftime('%Y-%m-%d %H:%M')}")
                                break
                            except Exception as exc:
                                if self.is_youtube_quota_error(exc):
                                    reset = next_pacific_midnight()
                                    retry_start = max(
                                        reset + timedelta(minutes=15),
                                        publish_at,
                                        local_now() + timedelta(minutes=15),
                                    )
                                    retry_interval = validate_interval_minutes(self.interval_var.get() or 5)
                                    # Rebuild all unaccepted YouTube slots after the quota reset.
                                    # The allocator keeps accepted posts untouched and enforces
                                    # the existing 100-slot Pacific-day cap for every later day.
                                    retry_rows = []
                                    for future_row in rows:
                                        retry_row = dict(future_row)
                                        future_status = str(retry_row.get("yt_status") or "Pending").strip().lower()
                                        if future_status not in {"scheduled", "published"}:
                                            retry_row["publish_at"] = None
                                        retry_rows.append(retry_row)
                                    retry_slots = allocate_youtube_publish_slots(
                                        retry_rows, retry_start, retry_interval, now=local_now()
                                    )
                                    updated_slots = 0
                                    for retry_path, retry_slot in retry_slots.items():
                                        self.db_execute(
                                            "UPDATE clips SET publish_at=? WHERE path=?",
                                            (retry_slot, retry_path)
                                        )
                                        for future_row in rows:
                                            if future_row["path"] == retry_path:
                                                future_row["publish_at"] = retry_slot
                                                break
                                        updated_slots += 1
                                    publish_at = datetime.fromisoformat(row["publish_at"]).astimezone()
                                    wait_seconds = max(30, (reset - local_now()).total_seconds())
                                    self.log(
                                        f"YouTube daily upload quota reached. {updated_slots} unaccepted YouTube "
                                        f"clips were moved to the next available quota windows, starting "
                                        f"{retry_start.strftime('%Y-%m-%d %H:%M')} local time, using the selected "
                                        f"{retry_interval}-minute interval and the 100-per-Pacific-day limit. "
                                        f"Pausing until quota reset at {reset.strftime('%Y-%m-%d %H:%M')}."
                                    )
                                    if self.stop_event.wait(wait_seconds):
                                        break
                                    continue
                                retry_at = max(
                                    publish_at + timedelta(days=1),
                                    local_now() + timedelta(days=1, minutes=15),
                                )
                                reason = str(exc)[:1100]
                                self.db_execute(
                                    "UPDATE clips SET yt_status='Error', yt_error=?, publish_at=? WHERE path=?",
                                    (f"{reason} | Retry slot reserved for {retry_at.strftime('%Y-%m-%d %H:%M')}. "
                                     "Reset failed and start the queue to retry.", retry_at.isoformat(), path)
                                )
                                self.log(
                                    f"YouTube rejected {name}: {exc}. Its retry slot is reserved for "
                                    f"{retry_at.strftime('%Y-%m-%d %H:%M')} local time tomorrow; "
                                    "use Reset failed and start the queue to retry it."
                                )
                                break

                if self.stop_event.is_set():
                    break

                if fb_enabled:
                    for page in selected_pages:
                        if self.stop_event.is_set():
                            break
                        page_id = str(page["id"])
                        job = self.get_fb_job(path, page_id)
                        if not job or job["status"] in {"Scheduled", "Published"} or job["status"].startswith("Skipped"):
                            continue
                        if row["fb_ok"] == 0:
                            self.db_execute(
                                "UPDATE facebook_page_jobs SET status='Skipped (format)', error=? WHERE path=? AND page_id=?",
                                ("Facebook Reel format pre-check failed (expected vertical 9:16, 4–60 seconds).", path, page_id)
                            )
                            self.log(f"Facebook skipped for {page.get('name')}: {name} (format)")
                            continue
                        try:
                            if not self.wait_for_fb_api_slot(page_id, page.get("name") or page_id):
                                break

                            publish_at = datetime.fromisoformat(job["publish_at"]).astimezone()
                            # Meta requires a scheduled publish time more than 10 minutes ahead.
                            # If the queue was paused/restarted, move this and subsequent posts
                            # forward rather than submitting an expired schedule time.
                            minimum_publish = local_now() + timedelta(minutes=15)
                            with self.db_lock:
                                last_scheduled = self.conn.execute(
                                    "SELECT MAX(publish_at) FROM facebook_page_jobs "
                                    "WHERE page_id=? AND status='Scheduled'",
                                    (page_id,)
                                ).fetchone()[0]
                            if last_scheduled:
                                last_dt = datetime.fromisoformat(last_scheduled).astimezone()
                                # A previously accepted post scheduled later than this
                                # confirmed batch must not push the new batch forward.
                                # Only preserve spacing when the latest accepted slot
                                # actually precedes this clip's assigned publish time.
                                if last_dt < publish_at:
                                    minimum_publish = max(minimum_publish, last_dt + timedelta(
                                        minutes=validate_interval_minutes(self.settings.get("interval", 5) or 5)
                                    ))
                            if publish_at < minimum_publish:
                                publish_at = minimum_publish
                                self.db_execute(
                                    "UPDATE facebook_page_jobs SET publish_at=? WHERE path=? AND page_id=?",
                                    (publish_at.isoformat(), path, page_id)
                                )
                                self.log(
                                    f"Adjusted Facebook schedule for {page.get('name')}: "
                                    f"{name} → {publish_at.strftime('%Y-%m-%d %H:%M')}"
                                )

                            self.log(f"Facebook Reel upload to {page.get('name')}: {name}")
                            video_id = self.upload_facebook_reel(
                                path, title, description, publish_at, fb_ai,
                                page_id=page_id, page_token=page["access_token"]
                            )
                            accepted_at = local_now().isoformat()
                            self.db_execute(
                                """UPDATE facebook_page_jobs
                                SET status='Scheduled', video_id=?, error=NULL, submitted_at=?
                                WHERE path=? AND page_id=?""",
                                (video_id, accepted_at, path, page_id)
                            )
                            self.log(
                                f"Facebook accepted on {page.get('name')}: {name} → "
                                f"{publish_at.strftime('%Y-%m-%d %H:%M')}"
                            )
                        except Exception as exc:
                            retry_base = datetime.fromisoformat(job["publish_at"]).astimezone()
                            retry_at = max(
                                retry_base + timedelta(days=1),
                                local_now() + timedelta(days=1, minutes=15),
                            )
                            reason = str(exc)[:1100]
                            self.db_execute(
                                "UPDATE facebook_page_jobs SET status='Error', error=?, publish_at=? WHERE path=? AND page_id=?",
                                (f"{reason} | Retry slot reserved for {retry_at.strftime('%Y-%m-%d %H:%M')}. "
                                 "Reset failed and start the queue to retry.", retry_at.isoformat(), path, page_id)
                            )
                            self.log(
                                f"Facebook rejected {name} on {page.get('name')}: {exc}. "
                                f"Its retry slot is reserved for {retry_at.strftime('%Y-%m-%d %H:%M')} "
                                "local time tomorrow; use Reset failed and start the queue to retry it."
                            )

                    self.update_fb_aggregate(path, selected_pages)

                self.organize_clip_after_upload(path, yt_enabled, fb_enabled, selected_pages)
                self.root.after(0, self.refresh_table)

            if self.stop_event.is_set():
                self.log("Queue stopped by user. Already accepted schedules remain; pending items are saved for resuming.")
            else:
                self.log("Queue processing finished. Check the per-Page statuses and cleanup report.")
        except Exception as exc:
            logger.exception("Queue worker crashed: %s", exc)
            self.log(f"Queue worker stopped: {exc}")
        finally:
            self.root.after(0, lambda: self.schedule_button.configure(state="normal"))
            self.root.after(
                0, lambda: self.stop_button.configure(state="disabled", text="Stop queue")
            )
            self.root.after(0, self.refresh_table)
            page_ids = [str(p["id"]) for p in selected_pages]
            self.root.after(
                0,
                lambda ids=page_ids, yt=yt_enabled, fb=fb_enabled: self.export_cleanup_report(
                    show_dialog=True,
                    selected_page_ids=ids,
                    include_youtube=yt,
                    include_facebook=fb
                )
            )

    def wait_for_fb_api_slot(self, page_id, page_name):
        """Wait until this app has fewer than 30 accepted Reel scheduling requests in 24h."""
        while not self.stop_event.is_set():
            now = local_now()
            cutoff = now - timedelta(hours=24)
            with self.db_lock:
                rows = self.conn.execute(
                    "SELECT submitted_at FROM facebook_page_jobs "
                    "WHERE page_id=? AND submitted_at IS NOT NULL",
                    (str(page_id),)
                ).fetchall()
            recent = []
            for row in rows:
                try:
                    submitted = datetime.fromisoformat(row["submitted_at"]).astimezone()
                    if submitted > cutoff:
                        recent.append(submitted)
                except Exception:
                    continue
            if len(recent) < 30:
                return True
            oldest = min(recent)
            resume_at = oldest + timedelta(hours=24, minutes=5)
            wait_seconds = max(1, (resume_at - now).total_seconds())
            self.log(
                f"Meta's 30-Reels-per-24h limit reached for {page_name}. "
                f"Pausing this Page until {resume_at.strftime('%Y-%m-%d %H:%M')} local time."
            )
            if self.stop_event.wait(wait_seconds):
                return False
        return False

    def update_fb_aggregate(self, path, selected_pages):
        statuses = []
        for page in selected_pages:
            job = self.get_fb_job(path, page["id"])
            statuses.append(job["status"] if job else "Pending")
        if not statuses:
            return
        normalized = [str(status).strip().lower() for status in statuses]
        if all(status == "published" for status in normalized):
            aggregate, error = "Published", None
        elif all(status in {"scheduled", "published"} for status in normalized):
            aggregate, error = "Scheduled", None
        elif any(status == "error" for status in normalized):
            aggregate = "Error"
            errors = [
                self.get_fb_job(path, page["id"]).get("error")
                for page in selected_pages
                if self.get_fb_job(path, page["id"]) and self.get_fb_job(path, page["id"]).get("error")
            ]
            error = "; ".join(errors)[:1500] if errors else "One or more Page uploads failed."
        elif any(status.startswith("Skipped") for status in statuses):
            aggregate, error = "Skipped (format)", "One or more selected Pages skipped this clip due to format."
        else:
            aggregate, error = "Pending", None
        self.db_execute(
            "UPDATE clips SET fb_status=?, fb_error=? WHERE path=?",
            (aggregate, error, path)
        )

    def is_youtube_quota_error(self, exc):
        message = str(exc).lower()
        content = getattr(exc, "content", b"")
        try:
            payload = json.loads(content.decode("utf-8", errors="ignore"))
            errors = payload.get("error", {}).get("errors", [])
            reasons = " ".join(str(e.get("reason", "")) for e in errors).lower()
            message += " " + reasons
        except Exception:
            pass
        return any(word in message for word in ("quotaexceeded", "dailylimitexceeded"))

    def upload_youtube(self, path, title, description, publish_at, contains_ai, made_for_kids, category_id):
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        creds = self.load_youtube_credentials(interactive=False)
        if not creds:
            raise RuntimeError("YouTube authorization expired. Reconnect from the Connections tab.")
        service = build("youtube", "v3", credentials=creds, cache_discovery=False)
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "categoryId": category_id or "20",
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at.isoformat(),
                "containsSyntheticMedia": bool(contains_ai),
                "selfDeclaredMadeForKids": bool(made_for_kids),
            }
        }
        media = MediaFileUpload(path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
        request = service.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            if self.stop_event.is_set():
                raise RuntimeError("Stopped before upload completed.")
            status, response = request.next_chunk()
            if status:
                self.log(f"YouTube upload progress: {int(status.progress() * 100)}% — {Path(path).name}")
        if not response or not response.get("id"):
            raise RuntimeError("YouTube returned no video ID after upload.")
        return response["id"]

    def upload_facebook_reel(self, path, title, description, publish_at, is_ai, page_id=None, page_token=None):
        token = page_token or self.secrets.get("fb_page_access_token", "")
        page_id = str(page_id or self.secrets.get("fb_page_id") or self.page_id_var.get().strip())
        if not token or not page_id:
            raise RuntimeError("Facebook Page access token or Page ID is missing.")

        start_response = requests.post(
            f"{GRAPH_BASE}/{page_id}/video_reels",
            data={"upload_phase": "START", "access_token": token},
            timeout=60
        )
        self.raise_graph_error(start_response)
        started = start_response.json()
        video_id = started.get("video_id")
        upload_url = started.get("upload_url")
        if not video_id or not upload_url:
            raise RuntimeError(f"Facebook did not return an upload session: {started}")

        file_size = os.path.getsize(path)
        headers = {
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(file_size),
            "Content-Type": "application/octet-stream",
        }
        with open(path, "rb") as video_file:
            upload_response = requests.post(
                upload_url, headers=headers, data=video_file, timeout=(60, 900)
            )
        self.raise_graph_error(upload_response)
        upload_data = upload_response.json() if upload_response.content else {}
        if upload_data and upload_data.get("success") is False:
            raise RuntimeError(f"Facebook binary upload failed: {upload_data}")

        finish_data = {
            "access_token": token,
            "video_id": video_id,
            "upload_phase": "FINISH",
            "video_state": "SCHEDULED",
            "scheduled_publish_time": str(int(publish_at.timestamp())),
            "title": title[:100],
            "description": description,
            "is_ai_generated": "true" if is_ai else "false",
        }
        finish_response = requests.post(
            f"{GRAPH_BASE}/{page_id}/video_reels",
            data=finish_data,
            timeout=90
        )
        self.raise_graph_error(finish_response)
        finished = finish_response.json()
        if finished.get("success") is False:
            raise RuntimeError(f"Facebook did not accept the scheduled Reel: {finished}")
        return str(finished.get("video_id") or video_id)

    @staticmethod
    def raise_graph_error(response):
        try:
            data = response.json()
        except Exception:
            data = {}
        if not response.ok or data.get("error"):
            error = data.get("error", {})
            message = error.get("message") or response.text[:1000] or f"HTTP {response.status_code}"
            code = error.get("code")
            subcode = error.get("error_subcode")
            raise RuntimeError(f"Facebook Graph API error {code or ''}/{subcode or ''}: {message}")

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "Uploads are running",
                "An upload/scheduling process is active. Closing now will stop it. "
                "Anything already scheduled on YouTube or Facebook will remain scheduled.\n\nClose anyway?"
            ):
                return
            self.stop_event.set()
        try:
            self.save_settings()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = SchedulerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
