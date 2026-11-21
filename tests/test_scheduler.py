import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from unittest.mock import patch

import app


class SchedulerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 22, 12, 0, tzinfo=ZoneInfo("Asia/Dhaka"))

    def test_youtube_retry_reallocates_expired_and_missing_publish_times(self):
        rows = [
            {"path": "accepted.mp4", "yt_status": "Scheduled",
             "publish_at": (self.now + timedelta(minutes=30)).isoformat()},
            {"path": "future.mp4", "yt_status": "Error",
             "publish_at": (self.now + timedelta(hours=1)).isoformat()},
            {"path": "expired.mp4", "yt_status": "Error",
             "publish_at": (self.now - timedelta(hours=1)).isoformat()},
            {"path": "missing.mp4", "yt_status": "Pending", "publish_at": None},
        ]
        start = self.now + timedelta(minutes=20)
        with patch.object(app, "local_now", return_value=self.now):
            slots = app.allocate_youtube_publish_slots(rows, start, 5, now=self.now)

        self.assertEqual(set(slots), {"expired.mp4", "missing.mp4"})
        self.assertEqual(rows[0]["publish_at"], (self.now + timedelta(minutes=30)).isoformat())
        self.assertEqual(rows[1]["publish_at"], (self.now + timedelta(hours=1)).isoformat())
        self.assertGreater(datetime.fromisoformat(slots["expired.mp4"]), self.now + timedelta(hours=1))
        self.assertGreater(datetime.fromisoformat(slots["missing.mp4"]),
                           datetime.fromisoformat(slots["expired.mp4"]))

    def test_youtube_retry_never_reschedules_an_accepted_post(self):
        rows = [
            {"path": "accepted.mp4", "yt_status": "Scheduled", "publish_at": None},
            {"path": "done.mp4", "yt_status": "Published", "publish_at": None},
        ]
        with patch.object(app, "local_now", return_value=self.now):
            slots = app.allocate_youtube_publish_slots(
                rows, self.now + timedelta(minutes=30), 5, now=self.now
            )
        self.assertEqual(slots, {})

    def test_youtube_allocator_keeps_each_pacific_day_at_or_below_100(self):
        start = app.next_pacific_midnight(self.now) + timedelta(hours=4)
        rows = [
            {"path": f"clip_{index:03}.mp4", "yt_status": "Pending", "publish_at": None}
            for index in range(208)
        ]
        slots = app.allocate_youtube_publish_slots(rows, start, 5, now=self.now)
        self.assertEqual(len(slots), 208)
        pacific = ZoneInfo("America/Los_Angeles")
        daily = {}
        for value in slots.values():
            day = datetime.fromisoformat(value).astimezone(pacific).date()
            daily[day] = daily.get(day, 0) + 1
        self.assertEqual(sorted(daily.values()), [8, 100, 100])
        self.assertLessEqual(max(daily.values()), 100)

    def test_youtube_allocator_moves_to_next_pacific_day_when_existing_day_is_full(self):
        pacific = ZoneInfo("America/Los_Angeles")
        quota_now = datetime(2026, 11, 22, 3, 0, tzinfo=pacific)
        first = quota_now + timedelta(hours=1)
        day = first.date()
        rows = [
            {"path": f"accepted_{index}.mp4", "yt_status": "Scheduled",
             "publish_at": (first + timedelta(minutes=index * 5)).isoformat()}
            for index in range(100)
        ]
        rows.append({"path": "retry.mp4", "yt_status": "Error", "publish_at": None})
        with patch.object(app, "local_now", return_value=quota_now):
            slots = app.allocate_youtube_publish_slots(
                rows, first, 5, now=quota_now
            )
        assigned = datetime.fromisoformat(slots["retry.mp4"]).astimezone(pacific)
        self.assertGreater(assigned.date(), day)
        self.assertEqual((assigned.hour, assigned.minute), (4, 0))

    def test_parse_txt_uses_first_nonempty_line_as_title_and_rest_as_description(self):
        with tempfile.TemporaryDirectory() as directory:
            txt = Path(directory) / "clip.txt"
            txt.write_text(
                "\ufeff\nA strong clip title\n\nFull transcript.\n#shorts\n"
                "Clip: clip.mp4\nTimestamp: 00:00:12 - 00:00:47\n",
                encoding="utf-8"
            )
            title, description = app.parse_txt(txt)
        self.assertEqual(title, "A strong clip title")
        self.assertIn("Full transcript.", description)
        self.assertIn("Timestamp:", description)

    def test_parse_txt_truncates_title_to_youtube_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            txt = Path(directory) / "clip.txt"
            txt.write_text("T" * 140 + "\nDescription", encoding="utf-8")
            title, description = app.parse_txt(txt)
        self.assertLessEqual(len(title), 100)
        self.assertEqual(description, "Description")

    def test_queue_status_requires_every_selected_destination(self):
        row = {"path": "clip.mp4", "yt_status": "Scheduled"}
        page_jobs = {
            ("clip.mp4", "page-a"): {"status": "Scheduled"},
            ("clip.mp4", "page-b"): {"status": "Pending"},
        }
        pages = [{"id": "page-a"}, {"id": "page-b"}]
        self.assertEqual(
            app.SchedulerApp.get_queue_row_status(row, page_jobs, pages, True, True),
            "◐ Partial"
        )
        page_jobs[("clip.mp4", "page-b")]["status"] = "Scheduled"
        self.assertEqual(
            app.SchedulerApp.get_queue_row_status(row, page_jobs, pages, True, True),
            "✓ Scheduled"
        )
        row["yt_status"] = "Published"
        page_jobs[("clip.mp4", "page-a")]["status"] = "Published"
        page_jobs[("clip.mp4", "page-b")]["status"] = "Published"
        self.assertEqual(
            app.SchedulerApp.get_queue_row_status(row, page_jobs, pages, True, True),
            "✓ Published"
        )

    def test_queue_status_marks_any_failed_destination_failed(self):
        row = {"path": "clip.mp4", "yt_status": "Scheduled"}
        jobs = {("clip.mp4", "page-a"): {"status": "Error"}}
        self.assertEqual(
            app.SchedulerApp.get_queue_row_status(
                row, jobs, [{"id": "page-a"}], True, True
            ),
            "⚠ Failed"
        )

    def test_safe_cleanup_gate_requires_every_recorded_destination_published(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.db_lock = threading.Lock()
            instance.conn = sqlite3.connect(":memory:")
            instance.conn.row_factory = sqlite3.Row
            instance.create_db()
            path_a = str(Path(directory) / "a.mp4")
            path_b = str(Path(directory) / "b.mp4")
            instance.db_execute(
                "INSERT INTO clips(path,title,description,yt_status,yt_video_id,publish_at) "
                "VALUES(?,?,?,?,?,?)",
                (path_a, "A", "", "Published", "yt-a", self.now.isoformat())
            )
            instance.db_execute(
                "INSERT INTO clips(path,title,description,yt_status,yt_video_id,publish_at) "
                "VALUES(?,?,?,?,?,?)",
                (path_b, "B", "", "Published", "yt-b", self.now.isoformat())
            )
            instance.db_execute(
                "INSERT INTO facebook_page_jobs(path,page_id,page_name,publish_at,status,video_id) "
                "VALUES(?,?,?,?,?,?)",
                (path_b, "page-a", "Page A", self.now.isoformat(), "Scheduled", "fb-b")
            )
            self.assertFalse(instance.all_recorded_destinations_published())
            instance.db_execute(
                "UPDATE facebook_page_jobs SET status='Published' WHERE path=?",
                (path_b,)
            )
            self.assertTrue(instance.all_recorded_destinations_published())
            instance.conn.close()

    def test_move_clip_files_moves_mp4_txt_and_database_paths_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "clip.mp4"
            txt = root / "clip.txt"
            video.write_bytes(b"test mp4")
            txt.write_text("Title\nDescription", encoding="utf-8")

            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.db_lock = threading.Lock()
            instance.conn = sqlite3.connect(":memory:")
            instance.conn.row_factory = sqlite3.Row
            instance.create_db()
            instance.folder_var = SimpleNamespace(get=lambda: str(root))
            instance.selected_path = str(video)
            instance.txt_preview_cache = {}
            instance.log = lambda _message: None
            instance.db_execute(
                "INSERT INTO clips(path,title,description) VALUES(?,?,?)",
                (str(video), "Title", "Description")
            )
            instance.db_execute(
                "INSERT INTO facebook_page_jobs(path,page_id,page_name,publish_at) VALUES(?,?,?,?)",
                (str(video), "page-a", "Page A", self.now.isoformat())
            )

            moved = Path(instance.move_clip_files(str(video), "schedule"))
            self.assertTrue(moved.is_file())
            self.assertEqual(moved.read_bytes(), b"test mp4")
            self.assertEqual(moved.with_suffix(".txt").read_text(encoding="utf-8"), "Title\nDescription")
            self.assertFalse(video.exists())
            self.assertFalse(txt.exists())
            self.assertEqual(instance.get_clips()[0]["path"], str(moved))
            self.assertEqual(instance.get_fb_job(str(moved), "page-a")["path"], str(moved))
            self.assertEqual(instance.selected_path, str(moved))
            instance.conn.close()

    def test_move_clip_files_restores_both_files_when_database_update_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "clip.mp4"
            txt = root / "clip.txt"
            video.write_bytes(b"test mp4")
            txt.write_text("Title\nDescription", encoding="utf-8")

            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.db_lock = threading.Lock()
            instance.conn = sqlite3.connect(":memory:")
            instance.conn.row_factory = sqlite3.Row
            instance.create_db()
            instance.folder_var = SimpleNamespace(get=lambda: str(root))
            instance.selected_path = None
            instance.txt_preview_cache = {}
            instance.log = lambda _message: None

            with self.assertRaisesRegex(RuntimeError, "queue record could not be updated"):
                instance.move_clip_files(str(video), "schedule")

            self.assertTrue(video.is_file())
            self.assertTrue(txt.is_file())
            self.assertFalse((root / "schedule" / "clip.mp4").exists())
            self.assertFalse((root / "schedule" / "clip.txt").exists())
            instance.conn.close()


if __name__ == "__main__":
    unittest.main()
