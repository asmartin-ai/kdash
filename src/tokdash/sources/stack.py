from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_AGENT_HUB_CATALOG_ENV = "AGENT_HUB_CATALOG"
_DEFAULT_CATALOG = Path("C:/Users/Kenja/agent-hub/config/catalog.json")
_DEFAULT_MODELS_TOML = Path("C:/Users/Kenja/agent-hub/config/models.toml")

_KNOWN_SERVICES = [
    ("127.0.0.1", 8788, "free-pool"),
    ("127.0.0.1", 55423, "kdash"),
    ("127.0.0.1", 8317, "cliproxyapi"),
    ("127.0.0.1", 9090, "openai-budget"),
    ("127.0.0.1", 1234, "lm-studio"),
    ("127.0.0.1", 8789, "macaron-stream-adapter"),
]

_DOCTOR_SCRIPT = Path("C:/Users/Kenja/agent-hub/scripts/doctor.py")
_DOCTOR_TIMEOUT = 10  # seconds


def _catalog_path() -> Path:
    env = os.environ.get(_AGENT_HUB_CATALOG_ENV)
    if env:
        return Path(env)
    return _DEFAULT_CATALOG


def _read_catalog() -> dict | None:
    """Read and return the catalog dict, or None if unavailable."""
    try:
        path = _catalog_path()
        if not path.exists():
            logger.warning("Catalog not found at %s", path)
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read catalog: %s", exc)
        return None


def _compute_staleness(catalog: dict | None) -> dict:
    """Check catalog freshness against models.toml SHA256."""
    if catalog is None:
        return {"status": "unknown", "remedy": "catalog not loaded"}
    try:
        toml_path = _DEFAULT_MODELS_TOML
        if not toml_path.exists():
            return {
                "status": "unknown",
                "remedy": f"models.toml not found at {toml_path}",
            }
        actual_sha = hashlib.sha256(toml_path.read_bytes()).hexdigest()
        catalog_sha = catalog.get("source_sha256", "")
        if actual_sha == catalog_sha:
            return {"status": "fresh", "remedy": None}
        return {
            "status": "stale",
            "remedy": "python config/render_models.py --format catalog",
        }
    except Exception as exc:
        return {"status": "unknown", "remedy": str(exc)}


def _find_model_for_role(
    role_value: str, models: dict
) -> tuple[str | None, dict | None]:
    """Match ``<provider>/<slug>`` to a catalog model entry.

    Returns ``(model_id, model_data)`` or ``(None, None)`` when unmatched.
    """
    slash = role_value.find("/")
    if slash == -1:
        return None, None
    provider_prefix = role_value[:slash]
    slug_remainder = role_value[slash + 1:]

    for model_id, model_data in models.items():
        for route in model_data.get("routes", []):
            if route.get("provider") == provider_prefix and route.get("slug") == slug_remainder:
                return model_id, model_data
    return None, None


def _collect_roles(catalog: dict | None) -> dict:
    """Extract the roles panel from the catalog."""
    if catalog is None:
        return {"status": "unavailable", "reason": "catalog not loaded"}

    roles_raw = catalog.get("routing", {}).get("roles", {})
    models = catalog.get("models", {})

    roles: dict[str, dict] = {}
    for role_name, role_value in roles_raw.items():
        model_id, model_data = _find_model_for_role(role_value, models)
        if model_data is not None:
            roles[role_name] = {
                "model": model_id,
                "display_name": model_data.get("display_name", model_id),
                "tier": f"T{model_data['tier']}" if "tier" in model_data else None,
                "context": model_data.get("context"),
                "cost_class": model_data.get("cost_class"),
            }
        else:
            roles[role_name] = {
                "model": role_value,
                "display_name": role_value,
                "tier": None,
                "context": None,
                "cost_class": None,
                "note": "not found in catalog (external provider)",
            }

    return {"status": "ok", "roles": roles}


def _collect_expiries(catalog: dict | None, today: date | None = None) -> dict:
    """Extract deadline entries from catalog.calendar, excluding stamps.

    ``today`` defaults to the local date; tests inject a fixed value so the
    day-count is deterministic (mirrors the TS ``collectExpiries(now)``).
    """
    if catalog is None:
        return {"status": "unavailable", "reason": "catalog not loaded"}

    if today is None:
        today = date.today()
    deadlines: list[dict] = []
    for entry in catalog.get("calendar", []):
        if entry.get("date_kind") != "deadline":
            continue
        raw = entry.get("date", "")
        try:
            entry_date = date.fromisoformat(raw)
        except (ValueError, TypeError):
            continue
        if entry_date < today:
            continue
        deadlines.append(
            {
                "date": raw,
                "days_remaining": (entry_date - today).days,
                "kind": entry.get("kind", ""),
                "id": entry.get("id", ""),
                "note": entry.get("note", ""),
            }
        )

    deadlines.sort(key=lambda d: d["days_remaining"])
    return {"status": "ok", "deadlines": deadlines}


def _probe_services() -> list[dict]:
    """TCP-connect probe of known local services."""
    results: list[dict] = []
    for host, port, label in _KNOWN_SERVICES:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            connected = sock.connect_ex((host, port)) == 0
            sock.close()
            status = "up" if connected else "down"
        except OSError:
            status = "down"
        results.append({"name": label, "host": host, "port": port, "status": status})
    return results


def _run_doctor() -> dict | None:
    """Run ``doctor.py --json`` and return parsed output, or None on failure."""
    try:
        proc = subprocess.run(
            [sys.executable, str(_DOCTOR_SCRIPT), "--json"],
            capture_output=True,
            text=True,
            timeout=_DOCTOR_TIMEOUT,
        )
        if proc.returncode not in (0, 1) and not proc.stdout.strip():
            logger.warning("doctor.py exited code %d with no stdout", proc.returncode)
            return None
        return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        logger.warning("doctor.py timed out after %ds", _DOCTOR_TIMEOUT)
        return None
    except Exception as exc:
        logger.warning("Failed to run doctor.py: %s", exc)
        return None


def _collect_health(doctor_result: dict | None) -> dict:
    """Extract the health panel from the doctor.py JSON result."""
    if doctor_result is None:
        return {"status": "unavailable", "reason": "doctor.py did not return data"}

    checks = doctor_result.get("checks", [])
    failing = [c["name"] for c in checks if c.get("status") == "FAIL"]
    warnings = [c["name"] for c in checks if c.get("status") == "WARN"]
    counts = doctor_result.get("counts", {})

    return {
        "status": "ok",
        "ok": bool(doctor_result.get("ok")),
        "counts": counts,
        "failing_checks": failing,
        "warning_checks": warnings,
    }


def collect_stack_snapshot() -> dict:
    """Collect the full stack-at-a-glance snapshot across all sources.

    Every source degrades independently: a missing catalog, a timed-out
    doctor subprocess, or a closed port affects only its own panel and
    never raises.
    """
    catalog = _read_catalog()

    # Each collector handles None internally.
    roles = _collect_roles(catalog)
    chains = {
        "status": "unavailable",
        "reason": (
            "Fallback chains live in omp's config.yml which kdash must not read "
            "or write. Consult omp config or modelRoles in ~/.omp/agent/config.yml."
        ),
    }
    expiries = _collect_expiries(catalog)
    services = _probe_services()
    doctor_result = _run_doctor()
    health = _collect_health(doctor_result)
    staleness = _compute_staleness(catalog)

    return {
        "roles": roles,
        "chains": chains,
        "expiries": expiries,
        "services": {"status": "ok", "probes": services},
        "health": health,
        "catalog_staleness": staleness,
    }
