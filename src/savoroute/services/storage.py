"""Validated JSON output persistence shared by ingestion pipelines."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from savoroute.ingestion.sources import IngestionError


def json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    data = json_text(payload)
    fd, temporary = tempfile.mkstemp(prefix=".savoroute-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json_pair(
    catalog_payload: dict[str, Any], report_payload: dict[str, Any], *,
    catalog_path: str | Path, report_path: str | Path, overwrite: bool = False,
) -> None:
    """Write two validated JSON documents. Atomic individually, not as a pair."""
    paths = (Path(catalog_path), Path(report_path))
    if paths[0].resolve() == paths[1].resolve():
        raise IngestionError("catalog and provenance/report paths must be distinct")
    if any(path.exists() for path in paths) and not overwrite:
        raise IngestionError("output already exists; choose new paths or pass --overwrite")
    for path in paths:
        if path.exists() and path.is_dir():
            raise IngestionError(f"output path is a directory: {path}")
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(paths[0], catalog_payload)
    _atomic_json(paths[1], report_payload)


def write_json_file(payload: dict[str, Any], path: str | Path, *, overwrite: bool = False) -> None:
    """Write a single JSON snapshot safely without overwriting by default."""
    target = Path(path)
    if target.exists() and not overwrite:
        raise IngestionError("snapshot already exists; choose a different path")
    if target.is_dir():
        raise IngestionError(f"output path is a directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(target, payload)
