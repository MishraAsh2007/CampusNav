"""One atomic snapshot is authoritative. Serving it never invokes a parser or network."""

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Snapshot


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, suffix=".tmp", encoding="utf-8", delete=False
        ) as handle:
            name = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


@contextmanager
def writer_lock(snapshot_path: Path):
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    lock = snapshot_path.with_suffix(".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("Another refresh holds the snapshot lock") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def read_snapshot(path: Path) -> Snapshot:
    return Snapshot.model_validate_json(path.read_text(encoding="utf-8"))


def active_closures(snapshot: Snapshot, now: datetime):
    return [
        c
        for c in snapshot.closures
        if c.start_time <= now and (c.end_time is None or c.end_time > now)
    ]


def snapshot_status(path: Path, now: datetime | None = None):
    now = now or datetime.now(UTC)
    try:
        snapshot = read_snapshot(path)
    except (OSError, ValueError):
        return {"status": "unavailable", "stale": True, "active_count": None}
    attempt_path = path.with_name(path.stem + ".status.json")
    try:
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        attempt = {}
    stale_sources = [
        s
        for s, observed in snapshot.source_observed_at.items()
        if now - observed > timedelta(hours=24)
    ]
    stale = (
        now - snapshot.generated_at > timedelta(hours=2)
        or bool(stale_sources)
        or attempt.get("status") in ("failed", "fallback")
        or any(s.mode in ("cache", "spreadsheet_fallback") for s in snapshot.source_status.values())
    )
    return {
        "status": "needs_review" if snapshot.counts.get("review", 0) else "ready",
        "stale": stale,
        "synthetic": snapshot.synthetic,
        "generated_at": snapshot.generated_at.isoformat(),
        "source_observed_at": {s: t.isoformat() for s, t in snapshot.source_observed_at.items()},
        "source_status": {s: t.model_dump(mode="json") for s, t in snapshot.source_status.items()},
        "stale_sources": stale_sources,
        "active_count": len(active_closures(snapshot, now)),
        "counts": snapshot.counts,
        "last_attempt": attempt,
    }
