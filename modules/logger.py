"""
logger.py — Structured Logging & Log Rotation System
Outputs JSON logs with daily rotation and 30-day archiving
"""

import json
import csv
import gzip
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger as loguru_logger


def setup_logging(log_dir: str = "./logs", level: str = "INFO"):
    """Configure loguru for application-wide structured logging."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    loguru_logger.remove()  # Remove default handler

    # Console — human-readable
    loguru_logger.add(
        sink=lambda msg: print(msg, end=""),
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File — JSON structured
    loguru_logger.add(
        f"{log_dir}/app_{{time:YYYY-MM-DD}}.log",
        level=level,
        rotation="00:00",        # Rotate at midnight
        retention="30 days",     # Keep 30 days
        compression="gz",        # Compress old logs
        serialize=True,          # JSON format
        enqueue=True,            # Thread-safe
    )

    return loguru_logger


class ActivityLogger:
    """
    Logs bot activities to structured JSON and CSV files.

    Log file: ./logs/requirements_log_{date}.json
    """

    def __init__(self, config: dict):
        self.log_dir     = Path(config["logging"]["log_dir"])
        self.archive_dir = Path(config["logging"]["archive_dir"])
        self.log_format  = config["logging"]["log_format"]
        self.rotation_days = config["logging"].get("rotation_days", 30)

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        self.today = datetime.utcnow().strftime("%Y-%m-%d")
        self.json_path = self.log_dir / f"requirements_log_{self.today}.json"
        self.csv_path  = self.log_dir / f"requirements_log_{self.today}.csv"

        self._init_json_log()
        self._init_csv_log()
        self._rotate_old_logs()

    def _init_json_log(self):
        """Initialize or load today's JSON log file."""
        if not self.json_path.exists():
            self.json_path.write_text("[]")

    def _init_csv_log(self):
        """Initialize today's CSV log with headers."""
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._csv_fields())
                writer.writeheader()

    def _csv_fields(self) -> list[str]:
        return [
            "timestamp", "post_url", "post_id", "company_name",
            "poster_name", "region", "country_code", "contact_email",
            "email_valid", "keyword_match", "email_sent", "email_sent_at",
            "date_posted", "date_crawled", "opted_out", "error"
        ]

    def log_post(
        self,
        post,
        email_sent: bool = False,
        email_sent_at: Optional[datetime] = None,
        error: str = ""
    ):
        """Log a discovered post + email status to JSON and CSV."""
        entry = {
            "timestamp":    datetime.utcnow().isoformat(),
            "post_url":     post.post_url,
            "post_id":      post.post_id,
            "company_name": post.company_name,
            "poster_name":  post.poster_name,
            "region":       post.region,
            "country_code": post.country_code,
            "contact_email": post.contact_email,
            "email_valid":  post.email_valid,
            "keyword_match": post.keyword_match,
            "email_sent":   "Y" if email_sent else "N",
            "email_sent_at": email_sent_at.isoformat() if email_sent_at else "",
            "date_posted":  post.date_posted.isoformat() if post.date_posted else "",
            "date_crawled": datetime.utcnow().isoformat(),
            "opted_out":    False,
            "error":        error,
        }

        # Append to JSON
        existing = json.loads(self.json_path.read_text())
        # Deduplicate by post_url
        urls = {e["post_url"] for e in existing}
        if entry["post_url"] not in urls:
            existing.append(entry)
            self.json_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False)
            )

        # Append to CSV
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._csv_fields())
            writer.writerow(entry)

    def log_session(self, session_data: dict):
        """Log a full crawl session summary."""
        session_path = (
            self.log_dir / f"session_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        )
        session_path.write_text(
            json.dumps(session_data, indent=2, default=str)
        )

    def _rotate_old_logs(self):
        """Archive log files older than rotation_days into compressed archives."""
        cutoff = datetime.utcnow() - timedelta(days=self.rotation_days)
        rotated = 0

        for log_file in self.log_dir.glob("requirements_log_*.json"):
            try:
                date_str = log_file.stem.replace("requirements_log_", "")
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                if file_date < cutoff:
                    archive_path = self.archive_dir / f"{log_file.name}.gz"
                    with open(log_file, "rb") as f_in:
                        with gzip.open(archive_path, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    log_file.unlink()
                    rotated += 1
            except (ValueError, Exception):
                continue

        if rotated:
            logging.info(f"🗄️ Archived {rotated} old log file(s).")

    def get_stats(self) -> dict:
        """Return today's log statistics."""
        entries = json.loads(self.json_path.read_text())
        sent   = sum(1 for e in entries if e["email_sent"] == "Y")
        valid  = sum(1 for e in entries if e["email_valid"])
        return {
            "date":          self.today,
            "total_logged":  len(entries),
            "emails_valid":  valid,
            "emails_sent":   sent,
            "pending_email": valid - sent,
        }
