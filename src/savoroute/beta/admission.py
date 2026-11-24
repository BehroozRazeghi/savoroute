"""Cross-process SQLite admission counters for optional paid endpoints.

Admission is charged BEFORE requesting a provider. It measures attempts, not
USD or model tokens; pair it with provider-side spending ceilings and an edge
access policy. There are intentionally no persistent prompts, images, raw IPs,
API keys or source URLs in this database.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import stat
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote


class AdmissionLimited(Exception):
    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AdmissionUnavailable(Exception):
    """An unavailable or corrupt store is a hard denial, never unlimited access."""


def _positive_int(value: str, key: str, *, maximum: int = 10000) -> int:
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= maximum:
        raise ValueError(f"{key} must be an integer between 1 and {maximum}")
    return int(value)


@dataclass(frozen=True)
class BetaPolicy:
    database: Path
    identity_secret: bytes
    ai_attempts_per_utc_day: int
    live_attempts_per_utc_day: int
    client_attempts_per_minute: int
    trusted_hosts: tuple[str, ...]

    @classmethod
    def from_environ(cls, env: Mapping[str, str]) -> BetaPolicy | None:
        enabled = env.get("SAVOROUTE_BETA_ENABLED", "0")
        if enabled not in {"0", "1"}:
            raise ValueError("SAVOROUTE_BETA_ENABLED must be 0 or 1")
        if enabled == "0":
            return None
        name = "SAVOROUTE_BETA_USAGE_DB"
        raw = env.get(name, "")
        db = Path(raw) if raw else Path(".")
        if not raw or not db.is_absolute() or db.name in {"", ".", ".."}:
            raise ValueError(f"{name} must be an absolute SQLite file path")
        secret = env.get("SAVOROUTE_BETA_IDENTITY_SECRET", "")
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("SAVOROUTE_BETA_IDENTITY_SECRET must be at least 32 bytes")
        host_raw = env.get("SAVOROUTE_BETA_TRUSTED_HOSTS", "")
        hosts = tuple(part.strip() for part in host_raw.split(",") if part.strip())
        if not hosts or any("*" in h or "/" in h or " " in h for h in hosts):
            raise ValueError("SAVOROUTE_BETA_TRUSTED_HOSTS requires explicit allowed hosts")
        return cls(
            database=db,
            identity_secret=secret.encode("utf-8"),
            ai_attempts_per_utc_day=_positive_int(
                env.get("SAVOROUTE_BETA_AI_DAILY", "20"), "SAVOROUTE_BETA_AI_DAILY"
            ),
            live_attempts_per_utc_day=_positive_int(
                env.get("SAVOROUTE_BETA_LIVE_DAILY", "10"), "SAVOROUTE_BETA_LIVE_DAILY"
            ),
            client_attempts_per_minute=_positive_int(
                env.get("SAVOROUTE_BETA_CLIENT_MINUTE", "3"),
                "SAVOROUTE_BETA_CLIENT_MINUTE", maximum=60,
            ),
            trusted_hosts=hosts,
        )


class BetaAdmission:
    """Atomic admission, shared across ASGI workers using the same DB file.

    A fixed UTC minute window bounds the number of requests per client/route.
    The global daily ceiling is independent of client identity. DB failures
    *deny* paid requests. Never trust an arbitrary X-Forwarded-For header here.
    """

    def __init__(self, policy: BetaPolicy) -> None:
        self.policy = policy
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        # mode=rw avoids silently recreating a removed budget database.
        # Refuse a replaced database: rebooting/replacing a budget file must
        # never silently reset paid-request counters mid-process.
        try:
            state = self.policy.database.lstat()
        except OSError as exc:
            raise AdmissionUnavailable("Beta admission storage is unavailable") from exc
        if (not stat.S_ISREG(state.st_mode) or
                getattr(self, "_device_inode", (state.st_dev, state.st_ino))
                != (state.st_dev, state.st_ino)):
            raise AdmissionUnavailable("Beta admission storage has changed")
        uri = f"file:{quote(self.policy.database.as_posix(), safe='/')}?mode=rw"
        con = sqlite3.connect(uri, uri=True, timeout=3, isolation_level=None)
        con.execute("PRAGMA busy_timeout=3000")
        return con

    def _initialize(self) -> None:
        path = self.policy.database
        if not path.parent.is_dir():
            raise ValueError("Beta usage database parent directory does not exist")
        if path.is_symlink():
            raise ValueError("Beta usage database cannot be a symlink")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if not path.is_file() or (path.stat().st_mode & 0o077):
                raise ValueError("Existing beta usage database must be a private regular file") from None
        else:
            os.close(fd)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("Beta usage database must be a regular file")
        state = path.stat()
        self._device_inode = (state.st_dev, state.st_ino)
        try:
            with self._connect() as con:
                con.execute("PRAGMA journal_mode=WAL")
                con.execute("PRAGMA synchronous=FULL")
                con.executescript("""
                    CREATE TABLE IF NOT EXISTS daily_attempts (
                        utc_day TEXT NOT NULL,
                        endpoint TEXT NOT NULL,
                        attempts INTEGER NOT NULL CHECK(attempts >= 0),
                        PRIMARY KEY (utc_day, endpoint)
                    );
                    CREATE TABLE IF NOT EXISTS minute_attempts (
                        utc_minute INTEGER NOT NULL,
                        endpoint TEXT NOT NULL,
                        client_fingerprint TEXT NOT NULL,
                        attempts INTEGER NOT NULL CHECK(attempts >= 0),
                        PRIMARY KEY (utc_minute, endpoint, client_fingerprint)
                    );
                """)
        except sqlite3.Error as exc:
            raise AdmissionUnavailable("Beta admission storage is unavailable") from exc

    def ready(self) -> bool:
        try:
            with self._connect() as con:
                return con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        except (AdmissionUnavailable, sqlite3.Error, OSError):
            return False

    def admit(self, endpoint: str, client_address: str, *, now: float | None = None) -> None:
        if endpoint not in {"ai", "live"}:
            raise ValueError("Unknown paid route")
        epoch = time.time() if now is None else now
        minute = int(epoch // 60)
        day = datetime.fromtimestamp(epoch, tz=UTC).date().isoformat()
        daily_limit = (
            self.policy.ai_attempts_per_utc_day if endpoint == "ai"
            else self.policy.live_attempts_per_utc_day
        )
        fingerprint = hmac.new(
            self.policy.identity_secret, client_address.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        try:
            con = self._connect()
            try:
                con.execute("BEGIN IMMEDIATE")
                day_count = con.execute(
                    "SELECT attempts FROM daily_attempts WHERE utc_day=? AND endpoint=?",
                    (day, endpoint),
                ).fetchone()
                if day_count is not None and day_count[0] >= daily_limit:
                    con.execute("ROLLBACK")
                    next_day = (minute // 1440 + 1) * 1440 * 60
                    raise AdmissionLimited("Daily beta capacity reached", max(1, int(next_day - epoch)))
                client_count = con.execute(
                    "SELECT attempts FROM minute_attempts "
                    "WHERE utc_minute=? AND endpoint=? AND client_fingerprint=?",
                    (minute, endpoint, fingerprint),
                ).fetchone()
                if (client_count is not None and
                        client_count[0] >= self.policy.client_attempts_per_minute):
                    con.execute("ROLLBACK")
                    raise AdmissionLimited("Too many requests; retry shortly", max(1, int((minute + 1) * 60 - epoch)))
                con.execute("""
                    INSERT INTO daily_attempts (utc_day, endpoint, attempts) VALUES (?, ?, 1)
                    ON CONFLICT(utc_day, endpoint) DO UPDATE SET attempts=attempts+1
                """, (day, endpoint))
                con.execute("""
                    INSERT INTO minute_attempts
                        (utc_minute, endpoint, client_fingerprint, attempts)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(utc_minute, endpoint, client_fingerprint)
                    DO UPDATE SET attempts=attempts+1
                """, (minute, endpoint, fingerprint))
                con.execute("DELETE FROM minute_attempts WHERE utc_minute < ?", (minute - 3,))
                con.execute("DELETE FROM daily_attempts WHERE utc_day < ?", (day,))
                con.execute("COMMIT")
            except BaseException:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise
            finally:
                con.close()
        except (AdmissionUnavailable, sqlite3.Error, OSError) as exc:
            raise AdmissionUnavailable("Beta admission storage is unavailable") from exc

    def totals(self, *, day: str | None = None) -> dict[str, int]:
        """Read only aggregate counts; for CLI use, never expose through HTTP."""
        selected = day or datetime.now(UTC).date().isoformat()
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT endpoint, attempts FROM daily_attempts WHERE utc_day=?", (selected,)
                ).fetchall()
                return {endpoint: attempts for endpoint, attempts in rows}
        except (AdmissionUnavailable, sqlite3.Error, OSError) as exc:
            raise AdmissionUnavailable("Beta admission storage is unavailable") from exc
