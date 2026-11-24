"""Show UTC daily attempt totals from a private beta admission DB (no PII)."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import quote


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Absolute path to existing private SQLite DB")
    parser.add_argument("--day", default=datetime.now(UTC).date().isoformat(),
                        help="UTC YYYY-MM-DD (default: current UTC day)")
    args = parser.parse_args()
    day = date.fromisoformat(args.day).isoformat()
    if not args.database.is_absolute() or not args.database.is_file():
        parser.error("Provide an existing absolute SQLite file path")
    uri = f"file:{quote(args.database.as_posix(), safe='/')}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=3) as connection:
            rows = connection.execute(
                "SELECT endpoint, attempts FROM daily_attempts WHERE utc_day=? ORDER BY endpoint",
                (day,),
            ).fetchall()
    except sqlite3.Error as exc:
        parser.error(f"Cannot inspect beta usage DB ({type(exc).__name__})")
    print(f"UTC day: {day} (attempts, not costs or tokens)")
    for name in ("ai", "live"):
        count = next((amount for route, amount in rows if route == name), 0)
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()
