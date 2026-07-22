from __future__ import annotations

import json
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ... import clientpaths
from .types import QuotaSnapshot


def _parse_time(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            number = float(value)
            return int(number / 1000) if number > 10_000_000_000 else int(number)
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return _parse_time(int(text))
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())
    except Exception:
        return None


def _normalize_percent(value: Any, *, unit_interval_as_fraction: bool = True) -> float | None:
    try:
        if value is None:
            return None
        pct = float(value)
    except Exception:
        return None
    if pct < 0:
        return None
    if unit_interval_as_fraction and 0.0 <= pct <= 1.0:
        return round(pct * 100.0, 4)
    return round(pct, 4)


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        part = str(token).split(".")[1]
        padded = part + "=" * (-len(part) % 4)
        data = base64.urlsafe_b64decode(padded.encode("ascii"))
        obj = json.loads(data.decode("utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _bucket_snapshot(
    *,
    rate_limits: dict[str, Any],
    bucket: str,
    bucket_label: str,
    bucket_payload: dict[str, Any],
    captured_at: int,
) -> QuotaSnapshot | None:
    used_percent = _normalize_percent(
        _first_present(bucket_payload, "used_percent", "usage_percent", "usedPercent"),
        unit_interval_as_fraction=False,
    )
    if used_percent is None:
        return None
    account = str(rate_limits.get("account_id") or "default")
    resets_at = _parse_time(_first_present(bucket_payload, "resets_at", "reset_at", "resetAt"))
    if not used_percent:
        # Codex's rolling-window API returns resets_at ~= captured_at + window_length even
        # for an idle window (0% used, timer hasn't actually started on first use yet). That
        # is a phantom reset, not a real one -- null it out so idle buckets render "reset --",
        # mirroring how Claude already treats its null buckets.
        resets_at = None
    return QuotaSnapshot(
        provider="codex",
        account=account,
        bucket=bucket,
        bucket_label=bucket_label,
        used_percent=used_percent,
        resets_at=resets_at,
        plan=str(rate_limits.get("plan_type") or "") or None,
        captured_at=captured_at,
        source="codex_session",
        status="ok",
        raw={"rate_limits": rate_limits},
    )


def snapshots_from_token_count_event(obj: dict[str, Any]) -> list[QuotaSnapshot]:
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    if obj.get("type") != "event_msg" or payload.get("type") != "token_count":
        return []
    captured_at = _parse_time(obj.get("timestamp"))
    if captured_at is None:
        return []
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    rate_limits = payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else {}
    if not rate_limits:
        rate_limits = info.get("rate_limits") if isinstance(info.get("rate_limits"), dict) else {}
    if not rate_limits:
        return []

    out: list[QuotaSnapshot] = []
    primary = rate_limits.get("primary") if isinstance(rate_limits.get("primary"), dict) else {}
    secondary = rate_limits.get("secondary") if isinstance(rate_limits.get("secondary"), dict) else {}
    if primary:
        snap = _bucket_snapshot(
            rate_limits=rate_limits,
            bucket="5h",
            bucket_label="5-hour window",
            bucket_payload=primary,
            captured_at=captured_at,
        )
        if snap:
            out.append(snap)
    if secondary:
        snap = _bucket_snapshot(
            rate_limits=rate_limits,
            bucket="7d",
            bucket_label="7-day window",
            bucket_payload=secondary,
            captured_at=captured_at,
        )
        if snap:
            out.append(snap)
    return out


QUOTA_SESSION_SOURCE = "codex_session"
_BACKFILL_META_KEY = "quota_codex_session_backfill_done"


def _downsample_snapshots(snapshots: list[QuotaSnapshot]) -> list[QuotaSnapshot]:
    """Keep the first observation per (provider, account, bucket, hour).

    Bounds row growth for both the one-time backfill (huge history) and per-cycle tail
    reads. Live polling is already coarse; the `INSERT OR IGNORE` UNIQUE key is the final
    dedup net, so this is purely a volume guard.
    """
    kept: dict[tuple[str, str, str, int], QuotaSnapshot] = {}
    for snapshot in sorted(snapshots, key=lambda item: item.captured_at):
        hour = snapshot.captured_at - (snapshot.captured_at % 3600)
        key = (snapshot.provider, snapshot.account, snapshot.bucket, hour)
        kept.setdefault(key, snapshot)
    return list(kept.values())


def _snapshots_from_bytes(data: bytes) -> tuple[list[QuotaSnapshot], int]:
    """Parse complete newline-terminated JSON lines out of ``data``.

    Returns ``(snapshots, consumed)`` where ``consumed`` is the number of bytes up to and
    including the last newline. A partial trailing line (Codex still mid-write) is left
    UNconsumed so it is re-read and parsed on a later cycle once it is complete.
    """
    last_nl = data.rfind(b"\n")
    if last_nl < 0:
        return [], 0
    out: list[QuotaSnapshot] = []
    for raw_line in data[: last_nl + 1].split(b"\n"):
        if not raw_line.strip():
            continue
        try:
            obj = json.loads(raw_line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.extend(snapshots_from_token_count_event(obj))
    return out, last_nl + 1


def _read_session_bytes(path: Path, offset: int) -> bytes:
    """Read from ``offset`` to EOF. Isolated so tests can count/observe file reads."""
    with open(path, "rb") as handle:
        if offset:
            handle.seek(offset)
        return handle.read()


def collect_codex_session_snapshots(sessions_dir: Path | None = None) -> list[QuotaSnapshot]:
    """Full rescan of every rollout file (no watermarks).

    Used for the DB-disabled fallback path where watermarks cannot be persisted. The
    incremental poll path uses :func:`collect_codex_session_snapshots_incremental`.
    """
    root = sessions_dir or clientpaths.codex_sessions_dir()
    if not root.exists():
        return []
    snapshots: list[QuotaSnapshot] = []
    for path in sorted(root.rglob("rollout-*.jsonl")):
        try:
            data = _read_session_bytes(path, 0)
        except OSError:
            continue
        found, _consumed = _snapshots_from_bytes(data)
        snapshots.extend(found)
    return _downsample_snapshots(snapshots)


def collect_codex_session_snapshots_incremental(
    store, sessions_dir: Path | None = None
) -> list[QuotaSnapshot]:
    """Watermark-based incremental session ingestion (mirrors ``file_state``).

    Each cycle stats every rollout file (no reads). Unchanged files (same mtime_ns + size)
    read ZERO bytes. Grown files seek to the stored offset and read only appended bytes,
    advancing the offset past the last complete line. Shrunken/rewritten files (size below
    the stored offset) drop the watermark and re-read whole; brand-new files read whole. The
    one-time full backfill (first run, no watermarks yet) reads everything once and records
    completion in the meta table so it never re-runs.
    """
    root = sessions_dir or clientpaths.codex_sessions_dir()
    if not root.exists():
        return []
    source = QUOTA_SESSION_SOURCE
    backfilled = store.quota_meta_get(_BACKFILL_META_KEY) == "1"
    watermarks = store.quota_file_watermarks(source)

    updates: list[tuple[str, int, int, int]] = []
    fresh: list[QuotaSnapshot] = []
    for path in sorted(root.rglob("rollout-*.jsonl")):
        try:
            stat = path.stat()
        except OSError:
            continue
        key = str(path)
        watermark = watermarks.get(key)
        if (
            watermark is not None
            and watermark["mtime_ns"] == stat.st_mtime_ns
            and watermark["size"] == stat.st_size
        ):
            continue  # unchanged: skipped with zero bytes read
        if watermark is None or stat.st_size < watermark["safe_offset"]:
            base = 0  # new file, or shrunk/rewritten -> re-read whole
        else:
            base = watermark["safe_offset"]  # grown/changed -> tail read
        try:
            data = _read_session_bytes(path, base)
        except OSError:
            continue
        found, consumed = _snapshots_from_bytes(data)
        fresh.extend(found)
        updates.append((key, stat.st_mtime_ns, stat.st_size, base + consumed))

    snapshots = _downsample_snapshots(fresh)
    # Snapshots and the watermarks that cover them commit in ONE transaction: if the
    # insert fails, the watermarks (and the backfill-done flag) roll back too, so the
    # next cycle re-reads the same bytes instead of skipping them forever.
    store.commit_quota_session_batch(
        snapshots,
        source,
        updates,
        backfill_meta_key=None if backfilled else _BACKFILL_META_KEY,
    )
    return snapshots


# Codex API collection replaced by omp.py (omp usage --json) 2026-07-22.
