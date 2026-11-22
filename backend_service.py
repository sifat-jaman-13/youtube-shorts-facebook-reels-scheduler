"""Headless ScarClipScheduler worker for the native WPF UI.

Only the WPF process owns windows and user interaction. This service reuses the
existing, tested YouTube/Meta upload and SQLite scheduling methods.
"""
from __future__ import annotations

import json
import secrets as secret_module
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import app as core


class Value:
    def __init__(self, value=None):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class RootBridge:
    def __init__(self, owner):
        self.owner = owner
        self.closed = False
    def after(self, milliseconds, callback):
        if self.closed:
            return
        # UI callbacks are translated into service events; no GUI event loop.
        try:
            callback()
        except Exception as exc:
            self.owner.log(f"Background callback failed: {exc}")
    def winfo_exists(self):
        return not self.closed


class ButtonStub:
    def configure(self, **_kwargs):
        pass


class TextStub:
    def configure(self, **_kwargs):
        pass
    def delete(self, *_args):
        pass
    def insert(self, *_args):
        pass


class DialogBridge:
    def __init__(self, owner):
        self.owner = owner
        self.confirm = False
    def showinfo(self, title, message):
        self.owner.emit("dialog", {"kind": "info", "title": str(title), "message": str(message)})
    def showwarning(self, title, message):
        self.owner.emit("dialog", {"kind": "warning", "title": str(title), "message": str(message)})
    def showerror(self, title, message):
        self.owner.emit("dialog", {"kind": "error", "title": str(title), "message": str(message)})
    def askyesno(self, title, message):
        self.owner.emit("confirmation", {"title": str(title), "message": str(message)})
        return bool(self.confirm)


def validate_future_start_at(value, now=None):
    """Require a schedule's first local post time to be strictly in the future."""
    try:
        start = datetime.strptime(str(value or "").strip(), "%Y-%m-%d %H:%M")
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a valid first post date and time (YYYY-MM-DD HH:mm).") from exc

    current = now if now is not None else datetime.now()
    if start <= current:
        raise ValueError("The first post date and time must be later than the current local time.")
    return start


class NativeBackend(core.SchedulerApp):
    def __init__(self):
        self.root = RootBridge(self)
        self.stop_event = threading.Event()
        self.worker = None
        self.scan_worker = None
        self.verification_worker = None
        self.youtube_auth_worker = None
        self.facebook_auth_worker = None
        self.db_lock = threading.RLock()
        self.conn = core.sqlite3.connect(core.DB_PATH, check_same_thread=False, timeout=30)
        self.conn.row_factory = core.sqlite3.Row
        self.create_db()

        self.settings = core.read_json(core.SETTINGS_PATH, {
            "folder": core.DEFAULT_FOLDER,
            "page_id": core.DEFAULT_PAGE_ID,
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
        self.secrets = core.read_json(core.CREDENTIALS_PATH, {
            "fb_page_access_token": "",
            "fb_page_name": "",
            "fb_page_id": "",
            "yt_channel_title": "",
            "yt_channel_id": "",
        })
        self.folder_var = Value(self.settings.get("folder", core.DEFAULT_FOLDER))
        self.start_var = Value(self.settings.get("start_at") or "")
        self.interval_var = Value(str(self.settings.get("interval", 5)))
        self.youtube_var = Value(bool(self.settings.get("youtube_enabled", True)))
        self.facebook_var = Value(bool(self.settings.get("facebook_enabled", True)))
        self.youtube_ai_var = Value(bool(self.settings.get("youtube_ai", False)))
        self.facebook_ai_var = Value(bool(self.settings.get("facebook_ai", False)))
        self.made_for_kids_var = Value(bool(self.settings.get("made_for_kids", False)))
        self.rights_confirm_var = Value(False)
        self.page_id_var = Value(self.settings.get("page_id", core.DEFAULT_PAGE_ID))
        self.business_id_var = Value(self.settings.get("business_id", ""))
        self.client_secrets_var = Value(self.settings.get("client_secrets", ""))
        self.meta_app_id_var = Value(self.settings.get("meta_app_id", ""))
        self.meta_app_secret_var = Value(self.settings.get("meta_app_secret", ""))
        self.category_var = Value(self.settings.get("category_id", "20"))
        self.connection_status_var = Value("")
        self.queue_summary_var = Value("")
        self.selection_title_var = Value("")
        self.selection_desc = TextStub()
        self.selection_title_entry = TextStub()
        self.selection_path = None
        self.selected_paths = []
        self.selected_path = None
        self.txt_preview_cache = {}
        self.tree_path_by_id = {}
        self.tree = None
        self.log_text = TextStub()
        self.schedule_button = ButtonStub()
        self.stop_button = ButtonStub()
        self.verification_button = ButtonStub()
        self.fb_page_vars = {}
        for page in (self.secrets.get("fb_pages") or []):
            page_id = str(page.get("id", ""))
            self.fb_page_vars[page_id] = Value(
                page_id in set(self.settings.get("fb_selected_page_ids") or [])
            )

        self.event_lock = threading.Lock()
        self.events = deque(maxlen=2500)
        self.next_event_id = 1
        self.dialogs = DialogBridge(self)
        core.messagebox = self.dialogs

    def emit(self, kind, data=None):
        with self.event_lock:
            event = {"id": self.next_event_id, "type": kind, "time": time.time(), "data": data or {}}
            self.next_event_id += 1
            self.events.append(event)

    def events_after(self, after_id):
        with self.event_lock:
            return [event for event in self.events if event["id"] > int(after_id)]

    def log(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        core.logger.info("%s", message)
        self.emit("log", {"message": f"[{stamp}] {message}"})

    def refresh_table(self):
        self.emit("state_changed")

    def refresh_connections(self):
        selected = set(self.settings.get("fb_selected_page_ids") or [])
        self.fb_page_vars = {
            str(page.get("id")): Value(str(page.get("id")) in selected)
            for page in (self.secrets.get("fb_pages") or [])
        }
        self.emit("state_changed")

    def get_selected_clip_paths(self):
        return list(self.selected_paths or [])

    def save_selected_pages(self):
        self.settings["fb_selected_page_ids"] = [
            page_id for page_id, var in self.fb_page_vars.items() if var.get()
        ]
        self.save_settings()
        self.emit("state_changed")

    def apply_page_selection(self, selected_ids):
        valid_ids = {str(page.get("id")) for page in (self.secrets.get("fb_pages") or [])}
        selected = {str(value) for value in (selected_ids or [])}
        selected &= valid_ids
        self.fb_page_vars = {
            str(page.get("id")): Value(str(page.get("id")) in selected)
            for page in (self.secrets.get("fb_pages") or [])
        }
        self.settings["fb_selected_page_ids"] = sorted(selected)
        self.save_settings()

    def apply_settings(self, data):
        if "folder" in data:
            self.folder_var.set(str(data["folder"]))
        if "start_at" in data:
            self.start_var.set(str(data["start_at"]))
        if "interval_minutes" in data:
            self.interval_var.set(str(max(1, min(core.MAX_INTERVAL_MINUTES, int(data["interval_minutes"])))))
        for key, var in (
            ("youtube_enabled", self.youtube_var),
            ("facebook_enabled", self.facebook_var),
            ("youtube_ai", self.youtube_ai_var),
            ("facebook_ai", self.facebook_ai_var),
            ("made_for_kids", self.made_for_kids_var),
        ):
            if key in data:
                var.set(bool(data[key]))
        if "category_id" in data:
            self.category_var.set(str(data["category_id"]))
        if "client_secrets" in data:
            self.client_secrets_var.set(str(data["client_secrets"]))
        if "meta_app_id" in data:
            self.meta_app_id_var.set(str(data["meta_app_id"]))
        if "meta_app_secret" in data and str(data["meta_app_secret"]).strip():
            # An empty PasswordBox means "leave the saved secret unchanged".
            self.meta_app_secret_var.set(str(data["meta_app_secret"]))
        if "business_id" in data:
            self.business_id_var.set(str(data["business_id"]))
        if "selected_paths" in data:
            self.selected_paths = [str(path) for path in (data["selected_paths"] or [])]
        if "rights_confirmed" in data:
            self.rights_confirm_var.set(bool(data["rights_confirmed"]))
        if "selected_page_ids" in data:
            self.apply_page_selection(data["selected_page_ids"])
        self.save_settings()

    def state(self):
        rows = self.get_clips()
        include_yt = bool(self.youtube_var.get())
        include_fb = bool(self.facebook_var.get())
        pages = self.get_selected_fb_pages() if include_fb else []
        with self.db_lock:
            jobs = self.conn.execute("SELECT * FROM facebook_page_jobs").fetchall()
        job_map = {(row["path"], str(row["page_id"])): dict(row) for row in jobs}
        page_names = {
            str(page.get("id")): page.get("name") or str(page.get("id"))
            for page in (self.secrets.get("fb_pages") or [])
        }
        decorated = []
        for row in rows:
            status = self.get_queue_row_status(
                row, job_map, pages, include_yt, include_fb
            )
            per_page = []
            for page in (self.secrets.get("fb_pages") or []):
                job = job_map.get((row["path"], str(page.get("id"))))
                if job:
                    per_page.append({
                        "page_id": str(page.get("id")),
                        "page_name": page_names.get(str(page.get("id")), ""),
                        "status": job.get("status") or "Pending",
                        "publish_at": job.get("publish_at") or "",
                        "error": job.get("error") or "",
                    })
            decorated.append({
                "path": row["path"],
                "file": Path(row["path"]).name,
                "title": row.get("title") or "",
                "description": row.get("description") or "",
                "duration": row.get("duration"),
                "width": row.get("width"),
                "height": row.get("height"),
                "fb_ok": row.get("fb_ok"),
                "queue_status": status,
                "yt_status": row.get("yt_status") or "Pending",
                "fb_status": row.get("fb_status") or "Pending",
                "publish_at": row.get("publish_at") or "",
                "yt_video_id": row.get("yt_video_id") or "",
                "facebook_pages": per_page,
            })
        decorated.sort(key=lambda item: self.queue_row_sort_key((item, item["queue_status"])))
        counts = {}
        for row in decorated:
            counts[row["queue_status"]] = counts.get(row["queue_status"], 0) + 1
        active = any(
            worker and worker.is_alive()
            for worker in (
                self.worker, self.scan_worker, self.verification_worker,
                self.youtube_auth_worker, self.facebook_auth_worker
            )
        )
        all_pages = [
            {
                "id": str(page.get("id")),
                "name": page.get("name") or str(page.get("id")),
                "selected": str(page.get("id")) in set(self.settings.get("fb_selected_page_ids") or []),
            }
            for page in (self.secrets.get("fb_pages") or [])
        ]
        return {
            "version": core.APP_VERSION,
            "folder": self.folder_var.get(),
            "start_at": self.start_var.get(),
            "interval_minutes": int(self.interval_var.get() or 5),
            "youtube_enabled": include_yt,
            "facebook_enabled": include_fb,
            "youtube_ai": self.youtube_ai_var.get(),
            "facebook_ai": self.facebook_ai_var.get(),
            "made_for_kids": self.made_for_kids_var.get(),
            "category_id": self.category_var.get(),
            "client_secrets": self.client_secrets_var.get(),
            "meta_app_id": self.meta_app_id_var.get(),
            "business_id": self.business_id_var.get(),
            "youtube_channel": self.secrets.get("yt_channel_title") or "",
            "youtube_channel_id": self.secrets.get("yt_channel_id") or "",
            "youtube_connected": bool(core.YT_TOKEN_PATH.exists()),
            "facebook_connected": bool(self.secrets.get("fb_pages") or self.secrets.get("fb_page_access_token")),
            "youtube_connecting": bool(self.youtube_auth_worker and self.youtube_auth_worker.is_alive()),
            "facebook_connecting": bool(self.facebook_auth_worker and self.facebook_auth_worker.is_alive()),
            "facebook_pages": all_pages,
            "rows": decorated,
            "counts": counts,
            "total": len(decorated),
            "busy": active,
            "queue_running": bool(self.worker and self.worker.is_alive()),
            "scan_running": bool(self.scan_worker and self.scan_worker.is_alive()),
            "verification_running": bool(self.verification_worker and self.verification_worker.is_alive()),
        }

    def start_scan(self, data):
        self.apply_settings(data)
        folder = Path(self.folder_var.get().strip())
        if not folder.is_dir():
            raise RuntimeError(f"Clip source folder does not exist: {folder}")
        for name in ("uploaded", "schedule", "You can delete these clips now"):
            (folder / name).mkdir(parents=True, exist_ok=True)
        safe_note = folder / "You can delete these clips now" / "READ ME FIRST.txt"
        if not safe_note.exists():
            safe_note.write_text(
                "Only API-verified published clips are moved here. This folder is for manual review; "
                "the application never deletes local video files.\n",
                encoding="utf-8"
            )
        if self.worker and self.worker.is_alive():
            raise RuntimeError("The publishing queue is currently running.")
        if any(worker and worker.is_alive() for worker in (self.youtube_auth_worker, self.facebook_auth_worker)):
            raise RuntimeError("Wait for account authorization to finish before scanning.")
        if self.scan_worker and self.scan_worker.is_alive():
            raise RuntimeError("A scan is already running.")
        self.scan_worker = threading.Thread(
            target=self._scan_worker, args=(folder,), daemon=True
        )
        self.scan_worker.start()
        self.emit("state_changed")

    def start_queue(self, data):
        if data.get("confirmed") is not True:
            raise RuntimeError("Scheduling was not sent with an explicit desktop user confirmation.")
        validate_future_start_at(data.get("start_at"))
        if any(worker and worker.is_alive() for worker in (self.youtube_auth_worker, self.facebook_auth_worker)):
            raise RuntimeError("Wait for account authorization to finish before scheduling.")
        self.dialogs.confirm = True
        self.apply_settings(data)
        # The user has already confirmed the complete scope in the native UI.
        core.SchedulerApp.start_scheduling(self)
        self.emit("state_changed")
        if self.worker and self.worker.is_alive():
            return {"started": True}
        return {"started": False}

    def stop_queue(self):
        core.SchedulerApp.stop_scheduling(self)
        self.emit("state_changed")

    def verify(self):
        core.SchedulerApp.check_publication_status(self, show_dialog=False)
        self.emit("state_changed")

    def _ensure_idle_for_auth(self):
        active = [
            worker for worker in (
                self.worker, self.scan_worker, self.verification_worker,
                self.youtube_auth_worker, self.facebook_auth_worker
            )
            if worker and worker.is_alive()
        ]
        if active:
            raise RuntimeError(
                "Wait for the active upload, scan, publication check, or account authorization to finish first."
            )

    def connect_youtube(self, data):
        self._ensure_idle_for_auth()
        self.apply_settings(data)
        token_path = core.YT_TOKEN_PATH
        backup_path = None
        if token_path.exists():
            backup_path = token_path.with_name(token_path.name + ".reconnect-backup")
            if backup_path.exists():
                backup_path.unlink()
            token_path.replace(backup_path)

        self.log("Starting Google OAuth. Complete sign-in in the browser to reconnect YouTube.")
        self.emit("state_changed")

        def authorize():
            try:
                credentials = self.load_youtube_credentials(interactive=True)
                if not credentials:
                    raise RuntimeError("Google did not return valid YouTube OAuth credentials.")
                from googleapiclient.discovery import build
                service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
                result = service.channels().list(part="snippet", mine=True).execute()
                items = result.get("items") or []
                if not items:
                    raise RuntimeError(
                        "No YouTube channel was returned for the Google account you authorized."
                    )
                channel = items[0]
                self.secrets["yt_channel_title"] = channel["snippet"]["title"]
                self.secrets["yt_channel_id"] = channel["id"]
                core.write_json(core.CREDENTIALS_PATH, self.secrets)
                if backup_path and backup_path.exists():
                    backup_path.unlink()
                self.log(
                    f"Connected YouTube channel: {channel['snippet']['title']} ({channel['id']})"
                )
                self.refresh_connections()
            except Exception as exc:
                # A failed reconnect must not strand the user without the old valid token.
                if token_path.exists():
                    token_path.unlink()
                if backup_path and backup_path.exists():
                    token_path.parent.mkdir(parents=True, exist_ok=True)
                    backup_path.replace(token_path)
                self.log(f"YouTube reconnection failed: {exc}")
                self.dialogs.showerror("YouTube connection failed", str(exc))
                self.refresh_connections()
            finally:
                self.youtube_auth_worker = None
                self.emit("state_changed")

        self.youtube_auth_worker = threading.Thread(target=authorize, daemon=True)
        self.youtube_auth_worker.start()
        return {"started": True}

    def connect_facebook(self, data):
        self._ensure_idle_for_auth()
        self.apply_settings(data)
        app_id = self.meta_app_id_var.get().strip()
        app_secret = self.meta_app_secret_var.get().strip()
        business_id = self.business_id_var.get().strip()
        if not app_id or not app_secret or not business_id:
            raise RuntimeError(
                "Enter the Meta App ID, App Secret and Business Portfolio ID before connecting."
            )
        self.log("Starting Facebook Business Portfolio authorization in your browser.")
        def authorize():
            try:
                self._facebook_oauth_worker(app_id, app_secret, business_id)
            finally:
                self.facebook_auth_worker = None
                self.emit("state_changed")
        self.facebook_auth_worker = threading.Thread(target=authorize, daemon=True)
        self.facebook_auth_worker.start()
        self.emit("state_changed")
        return {"started": True}

    def _ensure_idle_for_disconnect(self):
        self._ensure_idle_for_auth()

    def disconnect_youtube(self):
        self._ensure_idle_for_disconnect()
        token_path = core.YT_TOKEN_PATH
        if token_path.exists():
            token_path.unlink()
        self.secrets["yt_channel_title"] = ""
        self.secrets["yt_channel_id"] = ""
        core.write_json(core.CREDENTIALS_PATH, self.secrets)
        self.log(
            "YouTube disconnected on this PC. The local OAuth token was removed; "
            "existing YouTube schedules and their video IDs were not changed."
        )
        self.refresh_connections()
        return {"disconnected": True, "scheduled_posts_preserved": True}

    def disconnect_facebook(self):
        self._ensure_idle_for_disconnect()
        self.secrets.pop("fb_page_access_token", None)
        self.secrets.pop("fb_page_name", None)
        self.secrets.pop("fb_page_id", None)
        self.secrets.pop("fb_pages", None)
        core.write_json(core.CREDENTIALS_PATH, self.secrets)
        self.settings["fb_selected_page_ids"] = []
        self.fb_page_vars = {
            str(page.get("id", "")): Value(False)
            for page in (self.secrets.get("fb_pages") or [])
        }
        self.save_settings()
        self.log(
            "Facebook disconnected on this PC. Saved Page access tokens were removed; "
            "existing Page Reel schedules and recorded video IDs were not changed."
        )
        self.refresh_connections()
        return {"disconnected": True, "scheduled_posts_preserved": True}

    def save_metadata(self, data):
        path = str(data.get("path") or "")
        title = str(data.get("title") or "").strip()
        description = str(data.get("description") or "").strip()
        if not path or not title:
            raise ValueError("Select a clip and enter its title.")
        if len(title) > 100:
            raise ValueError("Titles must be 100 characters or fewer.")
        if len(description.encode("utf-8")) > 5000:
            raise ValueError("Descriptions must be 5,000 bytes or fewer.")
        self.db_execute(
            "UPDATE clips SET title=?, description=? WHERE path=?",
            (title, description, path)
        )
        self.log(f"Saved metadata override for {Path(path).name}")
        self.emit("state_changed")

    def delete_rows(self, data):
        paths = [str(path) for path in (data.get("paths") or [])]
        if not paths:
            raise ValueError("Select one or more clips first.")
        active = [
            worker for worker in (
                self.worker, self.scan_worker, self.verification_worker,
                self.youtube_auth_worker, self.facebook_auth_worker
            )
            if worker and worker.is_alive()
        ]
        if active:
            raise RuntimeError("Wait for scanning, publishing, verification, or account authorization to finish before removing queue rows.")
        removed = 0
        with self.db_lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                for path in paths:
                    self.conn.execute("DELETE FROM facebook_page_jobs WHERE path=?", (path,))
                    removed += self.conn.execute("DELETE FROM clips WHERE path=?", (path,)).rowcount
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        self.log(f"Removed {removed} queue row(s). MP4/TXT files and platform-side posts were left untouched.")
        self.emit("state_changed")
        return {"removed": removed}

    def reset_failed(self):
        core.SchedulerApp.reset_failed(self)
        self.emit("state_changed")

    def export_report(self):
        result = self.export_cleanup_report(show_dialog=False)
        return {"csv": result[0], "txt": result[1]}


BACKEND = None


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "ScarClipSchedulerNative/1.0"

    def log_message(self, *_args):
        return

    def _reply(self, status, value):
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _auth(self):
        supplied = self.headers.get("X-Scar-Token", "")
        return secret_module.compare_digest(supplied, self.server.api_token)

    def do_GET(self):
        if not self._auth():
            return self._reply(403, {"error": "Forbidden"})
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            return self._reply(200, BACKEND.state())
        if parsed.path == "/api/events":
            after = int((parse_qs(parsed.query).get("after") or ["0"])[0])
            return self._reply(200, {"events": BACKEND.events_after(after)})
        return self._reply(404, {"error": "Not found"})

    def do_POST(self):
        if not self._auth():
            return self._reply(403, {"error": "Forbidden"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 2_000_000:
                return self._reply(413, {"error": "Request too large"})
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            route = urlparse(self.path).path
            # The WPF client sends this only after the user accepts the
            # scheduling confirmation dialog. Keep the JSON flag for compatibility.
            if (
                route == "/api/schedule"
                and self.headers.get("X-Scar-User-Confirmed", "").strip().lower() == "true"
            ):
                data["confirmed"] = True
            handlers = {
                "/api/settings": lambda data: (BACKEND.apply_settings(data) or {"saved": True}),
                "/api/scan": BACKEND.start_scan,
                "/api/schedule": BACKEND.start_queue,
                "/api/stop": lambda _data: BACKEND.stop_queue(),
                "/api/verify": lambda _data: BACKEND.verify(),
                "/api/connect-youtube": BACKEND.connect_youtube,
                "/api/connect-facebook": BACKEND.connect_facebook,
                "/api/disconnect-youtube": lambda _data: BACKEND.disconnect_youtube(),
                "/api/disconnect-facebook": lambda _data: BACKEND.disconnect_facebook(),
                "/api/metadata": BACKEND.save_metadata,
                "/api/delete": BACKEND.delete_rows,
                "/api/reset-failed": lambda _data: BACKEND.reset_failed(),
                "/api/export-report": lambda _data: BACKEND.export_report(),
            }
            handler = handlers.get(route)
            if not handler:
                return self._reply(404, {"error": "Not found"})
            result = handler(data) or {"ok": True}
            return self._reply(200, result)
        except Exception as exc:
            BACKEND.emit("operation_error", {"message": str(exc)})
            return self._reply(400, {"error": str(exc)})


def main():
    global BACKEND
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    BACKEND = NativeBackend()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ApiHandler)
    server.daemon_threads = True
    server.api_token = args.token
    print(json.dumps({"ready": True, "port": server.server_address[1], "version": core.APP_VERSION}), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        BACKEND.root.closed = True
        BACKEND.conn.close()


if __name__ == "__main__":
    main()
