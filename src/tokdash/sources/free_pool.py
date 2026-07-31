"""Live free-pool (LiteLLM swarm) concurrency signal.

The scored suggestion registry (``tokdash.suggest``) models the free pool as a
couple of static lanes, but the real free pool on this workstation is a local
LiteLLM proxy whose lanes rotate as free trials appear, throttle, and expire.
This module reads the pool's own state file — the one maintained by the
``freepool watch`` sweep — and reports how many distinct *swarm* budgets are
currently healthy, using the same budget-dedup logic as ``freepool width``.

Returns ``None`` whenever the state is unavailable so the caller falls back to
the static registry estimate rather than inventing a number.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Default location of the free-pool state file on this machine. Overridable so
# the dashboard is not hard-coupled to one checkout path (and so tests can point
# at a fixture).
_DEFAULT_STATE = Path("K:/Projects/free-pool/state.json")

# Lanes whose last probe is older than this are treated as unknown, not healthy:
# a stale "ok" is not evidence the lane is up now.
_MAX_AGE_SECONDS = 24 * 3600


def _state_path() -> Path:
    override = os.environ.get("TOKDASH_FREE_POOL_STATE", "").strip()
    return Path(override) if override else _DEFAULT_STATE


def _parse_checked(value: object) -> Optional[float]:
    """Parse an ISO-8601 ``checked`` stamp to epoch seconds, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def free_pool_swarm_concurrency(
    *, group: str = "swarm", now: Optional[float] = None
) -> Optional[int]:
    """Distinct healthy budgets in the free-pool group, or None if unknown.

    Mirrors ``freepool width``: counts distinct ``api_key`` across lanes in the
    group whose last probe was ``ok`` and recent. Two lanes sharing a key are a
    single budget (running wider than the budget count only buys 429s). This
    under- rather than over-counts providers that meter per-key-per-model, which
    is the safe direction for a "how many agents can I spawn" hint.
    """
    path = _state_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    lanes = data.get("lanes") if isinstance(data, dict) else None
    if not isinstance(lanes, dict):
        return None

    base = now if now is not None else datetime.now(timezone.utc).timestamp()
    budgets: set[str] = set()
    saw_group = False
    for name, lane in lanes.items():
        if not isinstance(lane, dict):
            continue
        if str(lane.get("group") or "") != group:
            continue
        saw_group = True
        if not bool(lane.get("ok")):
            continue
        checked = _parse_checked(lane.get("checked"))
        if checked is not None and (base - checked) > _MAX_AGE_SECONDS:
            continue
        budgets.add(str(lane.get("api_key") or name))

    if not saw_group:
        return None
    return len(budgets)
