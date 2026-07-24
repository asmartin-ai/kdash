#!/usr/bin/env python3
"""Ambient tokdash glance — terminal plan dashboard.

Plan-usage-% first when a lane is subscription-shaped; metered lanes show
tokens and $ cost. Watch mode is a top-like alt-screen dashboard (in-place
refresh, not scrollback reprint).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone

from pathlib import Path
from typing import Any, Optional

TOKDASH = os.environ.get("TOKDASH_URL", "http://127.0.0.1:55423").rstrip("/")
PERIOD = os.environ.get("TOKDASH_STATUSLINE_PERIOD", "today")
DEFAULT_WATCH_S = int(os.environ.get("TOKDASH_GLANCE_INTERVAL", "120") or 120)
# ── Claude API throttle + disk cache ──
# Live oauth/usage is best-effort. Community pattern: cache last good % and
# label live|cached|local — file expiresAt alone is NOT "plan expired".
_CLAUDE_OAUTH_LAST_CALL: float = 0.0
_CLAUDE_LAST_PAYLOAD: dict = {}
_CLAUDE_LAST_PAYLOAD_AT: float = 0.0
_CLAUDE_OAUTH_COOLDOWN_S = float(os.environ.get("TOKDASH_CLAUDE_OAUTH_COOLDOWN", "300") or 300)
_CLAUDE_CACHE_MAX_AGE_S = float(
    os.environ.get("TOKDASH_CLAUDE_CACHE_MAX_AGE", str(48 * 3600)) or (48 * 3600)
)
_CLAUDE_429_BACKOFF_S = float(os.environ.get("TOKDASH_CLAUDE_429_BACKOFF", "900") or 900)
_CLAUDE_AUTH_FREEZE_UNTIL_MTIME: float | None = None  # freeze live fetch after 401
_CLAUDE_NEXT_LIVE_AFTER: float = 0.0  # monotonic; 429 backoff
NO_COLOR = os.environ.get("NO_COLOR") is not None or os.environ.get(
    "TOKDASH_GLANCE_NO_COLOR", ""
).strip() in {"1", "true", "yes"}
FORCE_COLOR = os.environ.get("FORCE_COLOR", "").strip() not in {"", "0"}
USE_COLOR = not NO_COLOR and (
    FORCE_COLOR
    or (sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb")
)

# Frame buffer for top-like watch: when set, render into this list instead of printing.
_FRAME: list[str] | None = None
# Compact dashboard collection (two-column compose after providers run).
_COMPACT = False
_RECORDS: list[dict[str, Any]] = []
_CUR_SECTION = ""


def _emit(s: str = "") -> None:
    """Write one display line (or blank). Watch mode buffers; one-shot prints."""
    if _COMPACT:
        return  # compose_dashboard paints later from _RECORDS
    if _FRAME is not None:
        _FRAME.append(s)
    else:
        print(s)


def _rec(kind: str, **kw: Any) -> None:
    if not _COMPACT:
        return
    _RECORDS.append({"kind": kind, "section": _CUR_SECTION, **kw})


_CTRL_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?")


def sanitize_display(value: Any) -> str:
    """Collapse external labels/errors to one printable line (no CR/LF/CSI)."""
    s = str(value if value is not None else "")
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    s = _ANSI_RE.sub("", s)
    s = _CTRL_RE.sub("", s)
    return " ".join(s.split())


PLAN_APPS = {
    a.strip().lower()
    for a in os.environ.get("TOKDASH_PLAN_APPS", "claude").split(",")
    if a.strip()
}
CLAUDE_5H_LIMIT = os.environ.get("TOKDASH_CLAUDE_5H_LIMIT", "").strip()
FIREWORKS_ACCOUNT = os.environ.get(
    "FIREWORKS_ACCOUNT_ID", "accounts/asmartin-ai"
).strip()
# SuperGrok trial (CLIProxyAPI) — REMOVED 2026-07-18 (trial lapsed, Grok unwired stack-wide).
# Freebuff — REMOVED 2026-07-22 (not in active rotation; dropped from suggest.py earlier).
# Agnes AI (Singapore free tier) — OpenAI-compatible hub; no public quota API.
AGNES_API_BASE = os.environ.get(
    "TOKDASH_AGNES_URL", "https://apihub.agnes-ai.com/v1"
).rstrip("/")
# Moonshot / Kimi direct OpenPlatform (T1 Kimi K3 wallet lane).
MOONSHOT_API_BASE = os.environ.get(
    "TOKDASH_MOONSHOT_URL", "https://api.moonshot.ai/v1"
).rstrip("/")

# ANSI
_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_RED = "\x1b[31m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_BLUE = "\x1b[34m"
_MAGENTA = "\x1b[35m"
_CYAN = "\x1b[36m"
_WHITE = "\x1b[37m"
_BG_DARK = "\x1b[48;5;236m"


def c(code: str, s: str) -> str:
    if not USE_COLOR:
        return s
    return f"{code}{s}{_RESET}"


def bold(s: str) -> str:
    return c(_BOLD, s)


def dim(s: str) -> str:
    return c(_DIM, s)


def _http_json(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    method: str = "GET",
    data: Optional[bytes] = None,
    timeout: float = 12.0,
) -> Any:
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {"Accept": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


def _get(url: str, timeout: float = 5.0) -> Any:
    return _http_json(url, timeout=timeout)


def fmt_tok(n: float) -> str:
    n = float(n or 0)
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}k"
    return f"{n:.0f}"


def pct_color(pct: float) -> str:
    if pct >= 90:
        return _RED
    if pct >= 70:
        return _YELLOW
    return _GREEN


def bar(pct: float, width: int = 10) -> str:
    p = max(0.0, min(float(pct), 100.0))
    filled = int(round(width * p / 100.0))
    empty = width - filled
    if USE_COLOR:
        col = pct_color(p)
        body = f"{col}{'█' * filled}{_DIM}{'░' * empty}{_RESET}"
        return f"[{body}]"
    return "[" + ("#" * filled) + ("-" * empty) + "]"


def fmt_pct(pct: float, *, already_pct: bool = True) -> str:
    p = float(pct)
    if not already_pct:
        p *= 100.0
    s = f"{p:5.1f}%"
    return c(pct_color(p) + _BOLD, s) if USE_COLOR else s


def section(title: str, subtitle: str = "") -> None:
    global _CUR_SECTION
    title_s = sanitize_display(title)
    sub_s = sanitize_display(subtitle)
    _CUR_SECTION = title_s
    _rec("section", title=title_s, subtitle=sub_s or "")
    if _COMPACT:
        return
    line = f" {title_s} "
    if sub_s:
        line = f" {title_s} · {sub_s} "
    pad = max(0, 58 - len(line))
    left = pad // 2
    right = pad - left
    raw = f"{'─' * left}{line}{'─' * right}"
    _emit(c(_CYAN + _BOLD, raw) if USE_COLOR else raw)


def kv_row(label: str, pct: float, extra: str = "") -> None:
    label_s = sanitize_display(label)
    extra_s = sanitize_display(extra)
    _rec("meter", label=label_s, pct=float(pct), extra=extra_s or "")
    if _COMPACT:
        return
    lab = f"{label_s:<14}"
    extra_out = f"  {dim(extra_s)}" if extra_s else ""
    _emit(f"  {lab} {fmt_pct(pct)} {bar(pct)}{extra_out}")


def info_row(label: str, value: str) -> None:
    label_s = sanitize_display(label)
    value_s = sanitize_display(value)
    _rec("info", label=label_s, value=value_s)
    if _COMPACT:
        return
    _emit(f"  {label_s:<14} {value_s}")


def warn_row(msg: str) -> None:
    msg_s = sanitize_display(msg)
    _rec("warn", msg=msg_s)
    if _COMPACT:
        return
    _emit(c(_YELLOW, f"  ! {msg_s}") if USE_COLOR else f"  ! {msg_s}")


def err_row(msg: str) -> None:
    msg_s = sanitize_display(msg)
    _rec("err", msg=msg_s)
    if _COMPACT:
        return
    _emit(c(_RED, f"  x {msg_s}") if USE_COLOR else f"  x {msg_s}")

def _ms_to_local(ms: Any) -> str:
    try:
        ts = float(ms)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except Exception:
        return "?"


def _iso_short(iso: Any) -> str:
    s = str(iso or "")
    if not s:
        return "?"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return s[:16]


def _iso_date(iso: Any) -> str:
    """Calendar date only (YYYY-MM-DD). Avoids the old [:10] trap on short strings."""
    s = str(iso or "").strip()
    if not s:
        return "?"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except Exception:
        # fall back: first YYYY-MM-DD-shaped token
        for tok in s.replace("T", " ").split():
            if len(tok) >= 10 and tok[4:5] == "-" and tok[7:8] == "-":
                return tok[:10]
        return s if len(s) >= 10 else (s or "?")


# ── tools ────────────────────────────────────────────────────────────────────


def glance_tools(period: str, *, show_cost: bool = False) -> int:
    try:
        d = _get(f"{TOKDASH}/api/tools?period={period}")
    except Exception as e:
        section("TOOLS")
        err_row(f"tokdash down ({TOKDASH})")
        _emit(dim(f"    {e}"))
        return 1

    apps = d.get("apps") or {}
    total_t = d.get("total_tokens") or 0
    total_c = float(d.get("total_cost") or 0)
    metered_cost = sum(
        float((a or {}).get("cost") or 0)
        for name, a in apps.items()
        if name.lower() not in PLAN_APPS
    )
    if show_cost:
        sub = f"{fmt_tok(total_t)}  ${total_c:.2f} rack-rate"
    elif metered_cost > 0:
        sub = f"{fmt_tok(total_t)}  metered ${metered_cost:.2f}"
    else:
        sub = f"{fmt_tok(total_t)}"
    section(f"TOOLS {period.upper()}", sub)

    for name, a in sorted(
        apps.items(), key=lambda kv: -float((kv[1] or {}).get("tokens") or 0)
    ):
        t = float((a or {}).get("tokens") or 0)
        cost = float((a or {}).get("cost") or 0)
        m = (a or {}).get("messages")
        is_plan = name.lower() in PLAN_APPS
        if is_plan and not show_cost:
            tag = dim("plan")
        elif cost > 0 or show_cost:
            tag = f"${cost:.3f}"
        else:
            tag = "$0"
        msgs = f"  msgs={m}" if m is not None else ""
        line = f"  {name:<14} {fmt_tok(t):>8}  {tag}{msgs}"
        if _COMPACT:
            _rec("raw", text=line)
        else:
            _emit(line)
    if not apps:
        info_row("(empty)", "no tool usage in period")
    return 0


# ── DEPRECATED: direct provider fetchers ──────────────────────────────────────
# Replaced 2026-07-22 by unified quota_state() path in render().
# Functions below are kept for test compatibility; remove in next cleanup pass.

def glance_zenmux() -> int:
    key = os.environ.get("ZENMUX_MANAGEMENT_API_KEY", "").strip()
    if not key:
        return 0
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def mgmt(path: str) -> dict:
        return _http_json(
            f"https://zenmux.ai/api/v1/management/{path}",
            headers=headers,
            timeout=15.0,
        )

    try:
        sub = mgmt("subscription/detail").get("data", {})
        try:
            payg = mgmt("payg/balance").get("data", {}).get("total_credits")
        except Exception:
            payg = None
    except Exception as e:
        section("ZENMUX")
        err_row(str(e))
        return 1

    plan = sub.get("plan", {})
    q5 = sub.get("quota_5_hour", {})
    q7 = sub.get("quota_7_day", {})
    p5 = 100 * float(q5.get("usage_percentage") or 0)
    p7 = 100 * float(q7.get("usage_percentage") or 0)
    # Remaining flow budget — shown next to bars (compact + classic).
    rem5 = float(q5.get("remaining_flows") or 0)
    max5 = float(q5.get("max_flows") or 0)
    rem7 = float(q7.get("remaining_flows") or 0)
    max7 = float(q7.get("max_flows") or 0)
    usd5 = float(q5.get("used_value_usd") or 0)
    max_usd5 = float(q5.get("max_value_usd") or 0)
    usd7 = float(q7.get("used_value_usd") or 0)
    max_usd7 = float(q7.get("max_value_usd") or 0)
    section(
        "ZENMUX",
        f"{str(plan.get('tier', '?')).upper()} · "
        f"{sub.get('account_status', '?')} · exp {_iso_date(plan.get('expires_at'))}",
    )
    # Priority in meter extra: flows left → reset day → $ (clip drops $ first).
    def _reset_label(raw: object) -> str:
        if raw is None or raw == "":
            return "—"
        s = _iso_short(raw)
        return "—" if s in {"?", ""} else s

    r5 = _reset_label(q5.get("resets_at"))
    r7 = _reset_label(q7.get("resets_at"))
    kv_row(
        "5-hour",
        p5,
        f"{rem5:.0f}/{max5:.0f} fl left · reset {r5}"
        f" · ${usd5:.2f}/${max_usd5:.2f}",
    )
    kv_row(
        "7-day",
        p7,
        f"{rem7:.0f}/{max7:.0f} fl left · reset {r7}"
        f" · ${usd7:.2f}/${max_usd7:.2f}",
    )
    # Dedicated lines so compact mode still shows day even if meter extra clips.
    # ~0.4 flows ≈ one medium M3 agent turn (≈50k in + 10k out at list rates).
    med_turns = max(0, int(rem7 / 0.4)) if rem7 else 0
    info_row(
        "flows left",
        f"5h {rem5:.0f}/{max5:.0f} · 7d {rem7:.0f}/{max7:.0f}"
        f" · ~{med_turns} med M3 turns",
    )
    info_row("resets", f"5h {r5} · 7d {r7}")
    if payg is not None:
        info_row("PAYG", f"${float(payg):.2f} metered fallback")
    return 0


# ── Claude ───────────────────────────────────────────────────────────────────


def _claude_state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "tokdash"
    return Path.home() / ".tokdash"


def _claude_cache_path() -> Path:
    return _claude_state_dir() / "claude_usage_cache.json"


def _claude_credentials_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


def _claude_credentials_mtime() -> float | None:
    try:
        return _claude_credentials_path().stat().st_mtime
    except Exception:
        return None


def _format_age(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    h, m = divmod(s, 3600)
    if h < 48:
        return f"{h}h{m // 60:02d}m" if m else f"{h}h"
    return f"{h // 24}d"


def _load_claude_usage_cache() -> tuple[dict, float] | None:
    """Return (payload, saved_at_epoch) if disk cache is present and not too old."""
    global _CLAUDE_LAST_PAYLOAD, _CLAUDE_LAST_PAYLOAD_AT
    path = _claude_cache_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = None
    if isinstance(raw, dict) and isinstance(raw.get("payload"), dict):
        try:
            saved = float(raw.get("saved_at") or 0)
        except Exception:
            saved = 0.0
        age = time.time() - saved if saved else 1e18
        if saved and age <= _CLAUDE_CACHE_MAX_AGE_S:
            _CLAUDE_LAST_PAYLOAD = raw["payload"]
            _CLAUDE_LAST_PAYLOAD_AT = saved
            return raw["payload"], saved
    # fall through to in-memory (same process watch)
    if _CLAUDE_LAST_PAYLOAD and _CLAUDE_LAST_PAYLOAD_AT:
        age = time.time() - _CLAUDE_LAST_PAYLOAD_AT
        if age <= _CLAUDE_CACHE_MAX_AGE_S:
            return _CLAUDE_LAST_PAYLOAD, _CLAUDE_LAST_PAYLOAD_AT
    return None


def _save_claude_usage_cache(payload: dict) -> None:
    global _CLAUDE_LAST_PAYLOAD, _CLAUDE_LAST_PAYLOAD_AT
    now = time.time()
    _CLAUDE_LAST_PAYLOAD = payload
    _CLAUDE_LAST_PAYLOAD_AT = now
    path = _claude_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {"saved_at": now, "payload": payload, "source": "oauth/usage"},
                indent=0,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        pass  # bars still work from memory this process


def _claude_access_token() -> tuple[Optional[str], dict[str, Any]]:
    env = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if env:
        return env, {
            "plan": None,
            "source": "env",
            "token_idle": False,
            "cred_mtime": None,
        }
    path = _claude_credentials_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        mtime = path.stat().st_mtime
    except Exception as e:
        return None, {"error": f"credentials: {e}", "cred_mtime": None}
    oauth = (
        data.get("claudeAiOauth")
        if isinstance(data.get("claudeAiOauth"), dict)
        else {}
    )
    token = oauth.get("accessToken")
    plan = oauth.get("subscriptionType") or data.get("subscriptionType")
    tier = oauth.get("rateLimitTier") or data.get("rateLimitTier")
    exp = oauth.get("expiresAt")
    meta: dict[str, Any] = {
        "plan": plan,
        "tier": tier,
        "expiresAt": exp,
        "source": str(path),
        "token_idle": False,  # file expiresAt past — not "plan expired"
        "cred_mtime": mtime,
        "has_refresh": bool(oauth.get("refreshToken")),
    }
    if not token:
        return None, {**meta, "error": "no accessToken"}
    try:
        if exp and int(exp) / 1000 <= time.time():
            meta["token_idle"] = True
    except Exception:
        pass
    return str(token), meta


def _claude_cli_logged_in() -> tuple[Optional[bool], dict[str, Any]]:
    """Best-effort Claude CLI login state. (None, {}) if CLI unavailable."""
    try:
        proc = subprocess.run(
            ["claude", "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip().startswith("{"):
            return None, {}
        st = json.loads(proc.stdout)
        return bool(st.get("loggedIn")), st
    except Exception:
        return None, {}


def glance_claude_window_local(*, as_fallback: bool = False) -> int:
    """Local ccusage 5h activity — not plan quota %. Label clearly."""
    blocks = _ccusage_blocks_json()
    if not blocks:
        if as_fallback:
            info_row("local", "ccusage unavailable · no cached plan bars")
        else:
            warn_row("ccusage unavailable for local 5h block")
        return 0
    candidates = [b for b in blocks if not b.get("isGap")]
    if not candidates:
        return 0
    active = [b for b in candidates if b.get("isActive")]
    block = (
        active[-1]
        if active
        else sorted(candidates, key=lambda b: str(b.get("startTime") or ""))[-1]
    )
    tokens = float(block.get("totalTokens") or 0)
    state = "active" if block.get("isActive") else "last window"
    limit = None
    if CLAUDE_5H_LIMIT and CLAUDE_5H_LIMIT.lower() not in {"max", "none", "off"}:
        try:
            limit = float(CLAUDE_5H_LIMIT.replace(",", "").replace("_", ""))
        except ValueError:
            limit = None
    label = "5h local"
    note = "activity not plan %"
    if limit and limit > 0:
        pct = 100.0 * tokens / limit
        kv_row(label, pct, f"{fmt_tok(tokens)}/{fmt_tok(limit)} · {state} · {note}")
    else:
        info_row(label, f"{state}  {fmt_tok(tokens)} tok · {note}")
    return 0


def _ccusage_blocks_json() -> list:
    candidates: list[list[str]] = []
    if shutil.which("ccusage"):
        candidates.append(["ccusage", "blocks", "--recent", "--json"])
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx:
        candidates.append([npx, "-y", "ccusage", "blocks", "--recent", "--json"])
    for cmd in candidates:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                shell=os.name == "nt",
            )
        except Exception:
            continue
        raw = (proc.stdout or "") + (proc.stderr or "")
        i = raw.find("{")
        if i < 0:
            continue
        try:
            data = json.loads(raw[i:])
        except json.JSONDecodeError:
            continue
        blocks = list(data.get("blocks") or [])
        if blocks:
            return blocks
    return []


def _claude_payload_has_bars(payload: dict) -> bool:
    """True if oauth/usage payload contains renderable quota rows."""
    if not isinstance(payload, dict):
        return False
    limits = payload.get("limits") if isinstance(payload.get("limits"), list) else []
    for limit in limits:
        if not isinstance(limit, dict):
            continue
        if limit.get("percent", limit.get("utilization")) is not None:
            return True
    for key in ("five_hour", "seven_day"):
        obj = payload.get(key)
        if isinstance(obj, dict) and (
            obj.get("utilization") is not None or obj.get("percent") is not None
        ):
            return True
    return False


def _claude_limit_label(limit: dict[str, Any]) -> str:
    """Human label for one oauth/usage limit row (avoid collapsing two weeklies to '7-day')."""
    kind = str(limit.get("kind") or limit.get("type") or "window")
    kind_l = kind.lower().replace("_", " ").replace("-", " ")
    if kind_l in {"session", "five hour", "5h", "5 hour"} or "five" in kind_l:
        return "session" if "session" in kind_l else "5-hour"
    if kind_l in {"weekly all", "weekly_all", "seven day", "7d", "7 day"} or (
        "week" in kind_l and "scoped" not in kind_l
    ):
        return "7-day"
    if "scoped" in kind_l or kind_l == "weekly scoped":
        scope = limit.get("scope") if isinstance(limit.get("scope"), dict) else {}
        model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
        name = str(model.get("display_name") or model.get("id") or "").strip()
        return f"7d {name}" if name else "7d scoped"
    if "week" in kind_l or "seven" in kind_l:
        return "7-day"
    return sanitize_display(kind)[:18] or "window"


def _claude_limit_is_noise(limit: dict[str, Any], used_f: float) -> bool:
    """Drop empty inactive scoped windows (e.g. Fable weekly at 0% with no reset)."""
    resets = limit.get("resets_at") if limit.get("resets_at") is not None else limit.get("resetsAt")
    active = limit.get("is_active")
    kind_l = str(limit.get("kind") or "").lower()
    if active is False and used_f <= 0.0 and not resets and "scoped" in kind_l:
        return True
    if active is False and used_f <= 0.0 and not resets and kind_l in {"", "window"}:
        return True
    return False


def _render_claude_payload(payload: dict, *, mode: str = "live") -> bool:
    """Render quota bars from an oauth/usage payload. True if any bar printed.

    mode: live | cached | stale — shown in meter extra so trust is visible.

    Claude's ``limits`` array can include both ``weekly_all`` and model-scoped
    weeklies (e.g. Fable). Older code labeled every weekly as ``7-day``, which
    produced two identical rows with the second often ``reset ?`` at 0%.
    """
    printed = False
    tag = {"live": "", "cached": " · cached", "stale": " · stale"}.get(mode, f" · {mode}")
    age_bit = ""
    if mode in {"cached", "stale"} and _CLAUDE_LAST_PAYLOAD_AT:
        age_bit = f" {_format_age(time.time() - _CLAUDE_LAST_PAYLOAD_AT)}"
    limits = payload.get("limits") if isinstance(payload.get("limits"), list) else []
    for limit in limits:
        if not isinstance(limit, dict):
            continue
        used = limit.get("percent")
        if used is None:
            used = limit.get("utilization")
        if used is None:
            continue
        try:
            raw_used = float(used)
        except (TypeError, ValueError):
            continue
        # API may send 0–1 fractions or already-percent values (0–100).
        used_f = raw_used * 100.0 if raw_used <= 1.5 else raw_used
        if _claude_limit_is_noise(limit, used_f):
            continue
        label = _claude_limit_label(limit)
        resets = limit.get("resets_at") or limit.get("resetsAt")
        reset_s = _iso_short(resets) if resets else "—"
        kv_row(label, used_f, f"reset {reset_s}{tag}{age_bit}")
        printed = True
    if not printed:
        for key, label in (("five_hour", "5-hour"), ("seven_day", "7-day")):
            obj = payload.get(key)
            if not isinstance(obj, dict):
                continue
            used = obj.get("utilization") if obj.get("utilization") is not None else obj.get("percent")
            if used is None:
                continue
            used_f = float(used)
            if used_f <= 1.5:
                used_f *= 100.0
            resets = obj.get("resets_at")
            reset_s = _iso_short(resets) if resets else "—"
            kv_row(
                label,
                used_f,
                f"reset {reset_s}{tag}{age_bit}",
            )
            printed = True
    return printed


def _render_claude_cached(*, prefer_disk: bool = True) -> bool:
    """Re-render last successful oauth/usage (memory or disk)."""
    if prefer_disk:
        loaded = _load_claude_usage_cache()
        if not loaded:
            return False
        payload, saved_at = loaded
        age = time.time() - saved_at
        mode = "cached" if age <= 6 * 3600 else "stale"
        return _render_claude_payload(payload, mode=mode)
    if not _CLAUDE_LAST_PAYLOAD:
        return False
    age = time.time() - _CLAUDE_LAST_PAYLOAD_AT
    mode = "cached" if age <= 6 * 3600 else "stale"
    return _render_claude_payload(_CLAUDE_LAST_PAYLOAD, mode=mode)


def _claude_show_fallback(mode_note: str = "") -> int:
    """Cached bars if any, else local activity. Returns 0."""
    if _render_claude_cached():
        if mode_note:
            info_row("meter", mode_note)
        return 0
    if mode_note:
        info_row("meter", mode_note)
    return glance_claude_window_local(as_fallback=True)


def glance_claude_plan() -> int:
    """Claude plan meters: live oauth/usage when possible, else disk-cached %.

    File expiresAt is advisory (token idle). Do not prescribe re-login when CLI
    is still logged in — refresh happens when Claude Code runs.
    """
    token, meta = _claude_access_token()
    plan = meta.get("plan") or "?"
    logged_in, cli_st = _claude_cli_logged_in()
    # Preload disk cache so cooldown/401 paths have bars across process restarts.
    _load_claude_usage_cache()
    return _glance_claude_plan_body(
        token=token,
        meta=meta,
        plan=str(plan),
        logged_in=logged_in,
        cli_st=cli_st,
    )


def _glance_claude_plan_body(
    *,
    token: Optional[str],
    meta: dict[str, Any],
    plan: str,
    logged_in: Optional[bool],
    cli_st: dict[str, Any],
) -> int:
    global _CLAUDE_OAUTH_LAST_CALL, _CLAUDE_AUTH_FREEZE_UNTIL_MTIME, _CLAUDE_NEXT_LIVE_AFTER

    def finish(mode: str, *, live_payload: dict | None = None, note: str = "") -> int:
        section("CLAUDE", f"plan={plan} · {mode}")
        if logged_in is True and cli_st.get("email"):
            # dim identity, not a second alarm
            info_row("cli", f"{cli_st.get('email')} · logged in")
        elif logged_in is False:
            warn_row("cli reports not logged in")
        if live_payload is not None:
            _save_claude_usage_cache(live_payload)
            _render_claude_payload(live_payload, mode="live")
            if note:
                info_row("token", note)
            return 0
        # cached / local path
        if _render_claude_cached():
            if note:
                info_row("token", note)
            return 0
        if note:
            info_row("token", note)
        return glance_claude_window_local(as_fallback=True)

    if not token:
        if logged_in is False:
            section("CLAUDE", f"plan={plan} · not logged in")
            err_row(meta.get("error") or "no OAuth token")
            warn_row("run: claude auth login")
            return glance_claude_window_local(as_fallback=True)
        return finish(
            "needs-refresh" if _load_claude_usage_cache() else "local",
            note=str(meta.get("error") or "no access token in credentials"),
        )

    cred_mtime = meta.get("cred_mtime")
    # Unfreeze if credentials file changed (Claude Code refreshed tokens).
    if (
        _CLAUDE_AUTH_FREEZE_UNTIL_MTIME is not None
        and cred_mtime is not None
        and float(cred_mtime) > float(_CLAUDE_AUTH_FREEZE_UNTIL_MTIME)
    ):
        _CLAUDE_AUTH_FREEZE_UNTIL_MTIME = None

    idle_note = ""
    if meta.get("token_idle"):
        idle_note = (
            f"access token idle since {_ms_to_local(meta.get('expiresAt'))}"
            " · refreshes on next claude use"
        )

    now_m = time.monotonic()

    # Frozen after 401 with same credentials mtime — do not re-hammer.
    if _CLAUDE_AUTH_FREEZE_UNTIL_MTIME is not None and (
        cred_mtime is None or float(cred_mtime) <= float(_CLAUDE_AUTH_FREEZE_UNTIL_MTIME)
    ):
        return finish(
            "cached" if _load_claude_usage_cache() else "needs-refresh",
            note=idle_note
            or "quota fetch paused — run any claude command to refresh meter",
        )

    # 429 backoff
    if now_m < _CLAUDE_NEXT_LIVE_AFTER:
        return finish(
            "cached" if _load_claude_usage_cache() else "local",
            note="quota API backoff after rate-limit",
        )

    # Normal cooldown: serve cache without network.
    # IMPORTANT: use finish() so section("CLAUDE") is recorded before meters.
    # Calling _render_claude_cached() first left meters under the prior section
    # (e.g. ZENMUX) in compact mode — intermittent layout bug.
    if now_m - _CLAUDE_OAUTH_LAST_CALL < _CLAUDE_OAUTH_COOLDOWN_S:
        if _load_claude_usage_cache():
            return finish("cached", note=idle_note)
        # no cache yet — fall through to live attempt once

    _CLAUDE_OAUTH_LAST_CALL = now_m

    url = "https://api.anthropic.com/api/oauth/usage"
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
    }
    try:
        payload = _http_json(url, headers=headers, timeout=15.0)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:160]
        if e.code in (401, 403):
            # Freeze live fetches until credentials file changes.
            if cred_mtime is not None:
                _CLAUDE_AUTH_FREEZE_UNTIL_MTIME = float(cred_mtime)
            else:
                _CLAUDE_AUTH_FREEZE_UNTIL_MTIME = time.time()
            note = idle_note or (
                "quota fetch needs token refresh — run any claude command "
                "(not auth login)"
            )
            if logged_in is False:
                section("CLAUDE", f"plan={plan} · not logged in")
                err_row(f"oauth/usage {e.code}")
                warn_row("run: claude auth login")
                if _render_claude_cached():
                    return 0
                return glance_claude_window_local(as_fallback=True)
            return finish(
                "cached" if _load_claude_usage_cache() else "needs-refresh",
                note=note,
            )
        if e.code == 429:
            _CLAUDE_NEXT_LIVE_AFTER = now_m + _CLAUDE_429_BACKOFF_S
            return finish(
                "cached" if _load_claude_usage_cache() else "local",
                note=f"rate-limited · backoff {_format_age(_CLAUDE_429_BACKOFF_S)}",
            )
        return finish(
            "cached" if _load_claude_usage_cache() else "local",
            note=f"oauth/usage HTTP {e.code}",
        )
    except Exception as e:
        return finish(
            "cached" if _load_claude_usage_cache() else "local",
            note=f"oauth/usage failed: {e}",
        )

    if isinstance(payload, dict) and _claude_payload_has_bars(payload):
        # success path: clear freeze/backoff; finish() saves + renders once
        _CLAUDE_AUTH_FREEZE_UNTIL_MTIME = None
        _CLAUDE_NEXT_LIVE_AFTER = 0.0
        return finish("live", live_payload=payload, note=idle_note)

    return finish(
        "cached" if _load_claude_usage_cache() else "local",
        note=f"no limit rows (keys={list(payload)[:8] if isinstance(payload, dict) else type(payload)})",
    )


# Codex (ChatGPT plan windows) section — REMOVED 2026-07-18 per user decision
# (free plan, no auth.json, can't refresh). Library code at src/tokdash/sources/quota/codex.py
# is left intact for future re-enablement.


# ── ClinePass ────────────────────────────────────────────────────────────────


def glance_clinepass() -> int:
    key = os.environ.get("CLINE_API_KEY", "").strip()
    if not key:
        return 0
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        plan = _http_json(
            "https://api.cline.bot/api/v1/users/me/plan", headers=headers
        )
        limits = _http_json(
            "https://api.cline.bot/api/v1/users/me/plan/usage-limits",
            headers=headers,
        )
        me = _http_json("https://api.cline.bot/api/v1/users/me", headers=headers)
    except Exception as e:
        section("CLINEPASS")
        err_row(str(e))
        return 1

    pdata = (plan or {}).get("data") or {}
    pinfo = pdata.get("plan") or {}
    name = pinfo.get("displayName") or pinfo.get("name") or "Cline Pass"
    # Short label — compact rail truncates subtitles; keep date intact.
    short_name = "Monthly" if "monthly" in name.lower() else name
    if len(short_name) > 14:
        short_name = short_name[:13] + "…"
    # currentPeriodEnd is ISO datetime — full date parse (never bare [:10]).
    end = _iso_date(pdata.get("currentPeriodEnd"))
    cancel_at = pdata.get("cancelAt")
    canceled_at = pdata.get("canceledAt")
    # Put date first so truncation can't produce "ends 2026-0".
    sub = f"ends {end}"
    if cancel_at or canceled_at:
        sub += f" · cancel {_iso_date(cancel_at or canceled_at)}"
    sub = f"{short_name} · {sub}"
    section("CLINEPASS", sub)

    label_map = {
        "five_hour": "5-hour",
        "weekly": "weekly",
        "monthly": "monthly",
    }
    for lim in ((limits or {}).get("data") or {}).get("limits") or []:
        if not isinstance(lim, dict):
            continue
        typ = str(lim.get("type") or "?")
        pct = float(lim.get("percentUsed") or 0)
        reset_val = lim.get("resetsAt")
        extra = f"reset {_iso_short(reset_val)}" if reset_val else ""
        kv_row(label_map.get(typ, typ), pct, extra)

    uid = ((me or {}).get("data") or {}).get("id")
    if uid:
        try:
            bal = _http_json(
                f"https://api.cline.bot/api/v1/users/{uid}/balance",
                headers=headers,
            )
            units = ((bal or {}).get("data") or {}).get("balance")
            if units is not None:
                info_row("balance units", f"{int(units):,}")
        except Exception:
            pass
    return 0


# ── Z.ai ─────────────────────────────────────────────────────────────────────


def glance_zai() -> int:
    key = os.environ.get("ZAI_API_KEY", "").strip()
    if not key:
        return 0
    headers = {
        "Authorization": key,  # raw token, no Bearer
        "Accept-Language": "en-US,en",
        "Content-Type": "application/json",
    }
    try:
        payload = _http_json(
            "https://api.z.ai/api/monitor/usage/quota/limit",
            headers=headers,
            timeout=15.0,
        )
    except Exception as e:
        section("Z.AI GLM")
        err_row(str(e))
        return 1

    data = (payload or {}).get("data") or {}
    limits = data.get("limits") or []
    section("Z.AI GLM", "Coding Plan")
    for lim in limits:
        if not isinstance(lim, dict):
            continue
        typ = str(lim.get("type") or "")
        unit, number = lim.get("unit"), lim.get("number")
        pct = float(lim.get("percentage") or 0)
        reset = lim.get("nextResetTime")
        if typ == "TOKENS_LIMIT" and unit == 3 and number == 5:
            label = "5h tokens"
        elif typ == "TOKENS_LIMIT" and unit == 6 and number == 1:
            label = "weekly tokens"
        elif typ == "TIME_LIMIT":
            label = "MCP monthly"
        else:
            label = f"{typ}:{unit}x{number}"
        extra = f"reset {_ms_to_local(reset)}"
        if typ == "TIME_LIMIT" and lim.get("usageDetails"):
            parts = [
                f"{d.get('modelCode')}={d.get('usage')}"
                for d in lim["usageDetails"]
                if isinstance(d, dict)
            ]
            if parts:
                extra += "  " + ",".join(parts[:3])
        kv_row(label, pct, extra)
    if not limits:
        warn_row(f"no limits ({(payload or {}).get('msg')})")
    return 0


# ── IAMHC.cn ──────────────────────────────────────────────────────────────────


def _beijing_hour() -> int:
    """Current hour in Beijing (UTC+8)."""
    return (datetime.now(timezone.utc).hour + 8) % 24


def _beijing_offpeak_window() -> tuple[bool, str]:
    """Return (is_offpeak_now, human description of window in local time)."""
    bj = _beijing_hour()
    offpeak = bj >= 22 or bj < 9
    # Next transition
    now = datetime.now(timezone.utc)
    if offpeak:
        # Currently off-peak → next peak starts at 09:00 Beijing = 01:00 UTC
        next_bj = 9
    else:
        # Currently peak → next off-peak starts at 22:00 Beijing = 14:00 UTC
        next_bj = 22
    next_utc = now.replace(hour=(next_bj - 8) % 24, minute=0, second=0, microsecond=0)
    if next_utc <= now:
        next_utc += timedelta(days=1)
    delta = next_utc - now
    h, m = int(delta.total_seconds() // 3600), int((delta.total_seconds() % 3600) // 60)
    # Local off-peak window description
    local_off_start = (22 - 8)  # 14:00 UTC = varies by local tz
    # Convert Beijing off-peak to local time for display
    bj_off_start = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)
    bj_off_end = bj_off_start + timedelta(hours=11)  # 22:00-09:00 BJT = 14:00-01:00 UTC
    local_start = bj_off_start.astimezone().strftime("%H:%M")
    local_end = bj_off_end.astimezone().strftime("%H:%M")
    window = f"off-peak {local_start}–{local_end} local"
    status = "off-peak" if offpeak else "peak"
    direction = "→ peak" if offpeak else "→ off-peak"
    return offpeak, f"{status} ({direction} in {h}h{m:02d}m)  {window}"


def glance_agnes() -> int:
    """Agnes free-tier lane — liveness + model inventory (no public quota API).

    Bakeoff 2026-07-15: free serial executor (2.0-flash); ~20 RPM / concurrency
    wall under parallel fan-out. 2.5-pro not live. Key: AGNES_API_KEY.
    """
    key = os.environ.get("AGNES_API_KEY", "").strip()
    if not key:
        return 0
    base = AGNES_API_BASE
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    ids: list[str] = []
    try:
        body = _http_json(f"{base}/models", headers=headers, timeout=12.0)
        raw = (body or {}).get("data") or (body or {}).get("models") or []
        for m in raw:
            if isinstance(m, dict) and m.get("id"):
                ids.append(str(m["id"]))
            elif isinstance(m, str):
                ids.append(m)
    except Exception as e:
        section("AGNES", "free serial")
        err_row(str(e))
        info_row("tip", "check AGNES_API_KEY · apihub.agnes-ai.com")
        return 1

    has_20 = any("2.0-flash" in i for i in ids)
    has_25 = any("2.5" in i for i in ids)
    status = "live" if has_20 else ("up" if ids else "empty models")
    section("AGNES", f"{status} · free serial · ~20 RPM")
    # Prefer coding models in the short list
    prefer = [i for i in ids if "flash" in i and "image" not in i and "video" not in i]
    other = [i for i in ids if i not in prefer]
    show = (prefer + other)[:4]
    info_row("api", base)
    info_row("models", " · ".join(show) if show else "(none)")
    if has_20 and not has_25:
        info_row("use", "agnes-2.0-flash · serial free · not parallel pool")
    elif has_25:
        info_row("use", "2.5 listed — prefer 2.0-flash until re-eval")
    else:
        info_row("use", "no 2.0-flash on /models — re-check key/catalog")
    info_row("tip", "429 = concurrency wall · bakeoff: Agnes > DS Flash > Hy3")
    return 0


def glance_moonshot() -> int:
    """Moonshot/Kimi direct wallet — balance + K3 catalog.

    Balance: GET {base}/users/me/balance (docs: platform.kimi.ai/docs/api/balance).
    Fields (USD): available_balance, cash_balance, voucher_balance.
    Stack T1 2026-07-17: model id `kimi-k3`. Key: MOONSHOT_API_KEY.
    """
    key = os.environ.get("MOONSHOT_API_KEY", "").strip()
    if not key:
        return 0
    base = MOONSHOT_API_BASE
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    # Balance is the primary meter — fail the section if it cannot load.
    bal_err: str | None = None
    available = cash = voucher = None
    try:
        bal = _http_json(f"{base}/users/me/balance", headers=headers, timeout=12.0) or {}
        if bal.get("code") not in (0, "0", None) and bal.get("status") is False:
            bal_err = f"balance code={bal.get('code')} scode={bal.get('scode')}"
        data = bal.get("data") if isinstance(bal.get("data"), dict) else bal
        if not isinstance(data, dict):
            bal_err = bal_err or "balance payload missing data"
        else:
            available = float(data.get("available_balance") or 0)
            cash = float(data.get("cash_balance") or 0)
            voucher = float(data.get("voucher_balance") or 0)
    except Exception as e:
        bal_err = str(e)

    if bal_err is not None and available is None:
        section("MOONSHOT", "Kimi direct")
        err_row(bal_err)
        info_row("tip", "check MOONSHOT_API_KEY · GET /v1/users/me/balance")
        return 1

    # Models catalog is secondary (best-effort).
    ids: list[str] = []
    models_err: str | None = None
    try:
        body = _http_json(f"{base}/models", headers=headers, timeout=12.0)
        raw = (body or {}).get("data") or (body or {}).get("models") or []
        for m in raw:
            if isinstance(m, dict) and m.get("id"):
                ids.append(str(m["id"]))
            elif isinstance(m, str):
                ids.append(m)
    except Exception as e:
        models_err = str(e)

    has_k3 = any(i == "kimi-k3" or i.endswith("/kimi-k3") for i in ids)
    if available is not None and available <= 0:
        status = "EMPTY"
    elif has_k3:
        status = "k3 live"
    elif ids:
        status = "up"
    else:
        status = "wallet"

    section("MOONSHOT", f"{status} · ${available:.2f} avail")
    info_row(
        "balance",
        f"${available:.2f} avail  "
        f"(cash ${cash:.2f} · voucher ${voucher:.2f})",
    )
    if available is not None and available <= 0:
        warn_row("available_balance ≤ 0 — inference will fail until top-up")
    prefer = [i for i in ids if "kimi-k3" in i or i.startswith("kimi-k")]
    other = [i for i in ids if i not in prefer]
    show = (prefer + other)[:5]
    if show:
        info_row("models", " · ".join(show))
    elif models_err:
        info_row("models", f"(error) {models_err}")
    else:
        info_row("models", "(none)")
    if has_k3:
        info_row("use", "kimi-k3 · T1 · ~$3/$15 per M list · temp=1 only")
    else:
        info_row("use", "kimi-k3 missing from /models — re-check key/catalog")
    info_row("tip", "prefer direct wallet over OpenRouter · balance is USD")
    return 0


def glance_iamhc() -> int:
    key = os.environ.get("IAMHC_API_KEY", "").strip()
    if not key:
        return 0
    headers = {"Authorization": f"Bearer {key}"}
    offpeak, peak_note = _beijing_offpeak_window()

    # Usage
    usage_str = "?"
    try:
        body = _http_json(
            "https://api.iamhc.cn/v1/dashboard/billing/usage",
            headers=headers,
            timeout=10.0,
        )
        total = float((body or {}).get("total_usage") or 0)
        usage_str = f"¤{total:,.1f} used"
    except Exception:
        pass

    status_icon = "🌙" if offpeak else "☀️"
    section(f"IAMHC {status_icon}", usage_str)
    info_row("window", peak_note)
    info_row("models", "28 (DS V4 Pro/Flash, GLM 5.2, M3, Qwen3.5, …)")
    info_row("tip", "free tier · daily check-in ~¤1,000/day · no expiry")
    return 0


# ── Fireworks ────────────────────────────────────────────────────────────────


def glance_fireworks() -> int:
    """Minimal Fireworks lane: 30d usage only.

    Docs: GET /v1/accounts/{id}/billingUsage — usage metrics (tokens / costNanoUsd),
    not wallet balance. No public balance endpoint; keep this section short.
    """
    key = os.environ.get("FIREWORKS_API_KEY", "").strip()
    if not key:
        return 0
    acc = FIREWORKS_ACCOUNT
    if not acc.startswith("accounts/"):
        acc = f"accounts/{acc}"
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    url = (
        f"https://api.fireworks.ai/v1/{acc}/billingUsage"
        f"?startTime={start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        f"&endTime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    try:
        data = _http_json(
            url, headers={"Authorization": f"Bearer {key}"}, timeout=20.0
        )
    except Exception as e:
        section("FIREWORKS")
        err_row(str(e))
        return 1

    rows = (data or {}).get("serverlessCosts") or []
    prompt = sum(int(r.get("promptTokens") or 0) for r in rows)
    completion = sum(int(r.get("completionTokens") or 0) for r in rows)
    total = prompt + completion
    # costNanoUsd is integer nano-USD when present
    nano = sum(int(r.get("costNanoUsd") or 0) for r in rows)
    cost_usd = nano / 1e9 if nano else 0.0
    # billingUsage is usage-only — no public wallet balance endpoint.
    section("FIREWORKS", "30d usage (not wallet)")
    if cost_usd > 0:
        info_row("30d used", f"{fmt_tok(total)} tok · ~${cost_usd:.2f}")
    else:
        info_row("30d used", f"{fmt_tok(total)} tok · $n/a")
    return 0

# ── OpenRouter ───────────────────────────────────────────────────────────────


def glance_openrouter() -> int:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return 0
    headers = {"Authorization": f"Bearer {key}"}
    try:
        kd = (_http_json("https://openrouter.ai/api/v1/key", headers=headers) or {}).get("data") or {}
        cd = (_http_json("https://openrouter.ai/api/v1/credits", headers=headers) or {}).get("data") or {}
    except Exception as e:
        section("OPENROUTER")
        err_row(str(e))
        return 1
    total = float(cd.get("total_credits") or 0)
    used = float(cd.get("total_usage") or 0)
    tier = "free tier" if kd.get("is_free_tier") else "paid"
    section("OPENROUTER", tier)
    if total > 0:
        pct = 100.0 * used / total
        kv_row("credits", pct, f"${used:.2f} / ${total:.2f}  (${total - used:.2f} left)")
    else:
        info_row("credits", f"${used:.2f} used · no credits purchased")
    limit = kd.get("limit")
    if limit is not None:
        rem = kd.get("limit_remaining")
        info_row("key limit", f"${float(limit):.2f}  (remaining ${float(rem or 0):.2f})")
    d, w, m = (float(kd.get(k) or 0) for k in ("usage_daily", "usage_weekly", "usage_monthly"))
    if d or w or m:
        info_row("usage", f"day ${d:.2f} · week ${w:.2f} · month ${m:.2f}")
    return 0


# ── DeepSeek ─────────────────────────────────────────────────────────────────


def glance_deepseek() -> int:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return 0
    try:
        data = _http_json(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {key}"},
        )
    except Exception as e:
        section("DEEPSEEK")
        err_row(str(e))
        return 1
    infos = (data or {}).get("balance_infos") or []
    if not infos:
        return 0
    b = infos[0]
    section("DEEPSEEK", str(b.get("currency") or "USD"))
    info_row(
        "balance",
        f"${float(b.get('total_balance') or 0):.2f}  "
        f"(topup ${float(b.get('topped_up_balance') or 0):.2f})",
    )
    return 0


# ── render ───────────────────────────────────────────────────────────────────


def _strip_ansi(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\x1b":
            i += 1
            if i < len(s) and s[i] == "[":
                i += 1
                while i < len(s) and not (64 <= ord(s[i]) <= 126):
                    i += 1
                i += 1
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _visible_len(s: str) -> int:
    return len(_strip_ansi(s))


def _pad_visible(s: str, width: int) -> str:
    """Pad or clip to *exactly* ``width`` visible cells (stable right-rail column)."""
    plain = _strip_ansi(s)
    n = len(plain)
    if n == width:
        return plain  # exact fit — keep full text (e.g. …·07-18)
    if n < width:
        # Prefer plain padding for stable columns (colors inside left column ok).
        return s + (" " * (width - n))
    # Over-wide: prefer cutting at separator so dates/resets stay intact.
    cut = plain[: max(0, width - 1)]
    for sep in (" · ", " ", "·"):
        idx = cut.rfind(sep)
        if idx >= 12:
            cut = cut[:idx]
            break
    if len(cut) >= width:
        cut = plain[: max(0, width - 1)]
    out = cut.rstrip(" ·") + "…"
    # CRITICAL: after rstrip the result can be shorter than width; pad so the
    # right SUGGEST rail starts in the same column on every row (72-col bug).
    if len(out) < width:
        out = out + (" " * (width - len(out)))
    elif len(out) > width:
        out = out[: max(0, width - 1)] + "…"
    return out


def _parse_reset_hint(extra: str) -> tuple[Optional[datetime], str]:
    """Best-effort extract a reset/expiry datetime from meter extra text."""
    s = extra or ""
    for key in ("reset ", "exp ", "ends "):
        i = s.lower().find(key)
        if i < 0:
            continue
        frag = s[i + len(key) :].strip().split()[0:2]
        token = " ".join(frag).strip(" ·,;")
        now = datetime.now()
        for fmt in ("%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m-%d"):
            try:
                piece = token
                if fmt == "%m-%d %H:%M" and len(token) >= 11:
                    piece = token[:11]
                elif fmt == "%Y-%m-%d" and len(token) >= 10:
                    piece = token[:10]
                elif fmt == "%m-%d" and len(token) >= 5:
                    piece = token[:5]
                dt = datetime.strptime(piece, fmt)
                if fmt.startswith("%m"):
                    dt = dt.replace(year=now.year)
                    if dt < now - timedelta(days=180):
                        dt = dt.replace(year=now.year + 1)
                return dt, token
            except Exception:
                continue
        return None, token
    return None, ""


def _section_peak(records: list[dict[str, Any]], prefix: str) -> float | None:
    """Hottest meter % for any section whose title starts with prefix (casefold)."""
    pref = prefix.casefold()
    peaks: list[float] = []
    for r in records:
        if r.get("kind") != "meter":
            continue
        sec = str(r.get("section") or "")
        if sec.casefold().startswith(pref):
            peaks.append(float(r.get("pct") or 0))
    return max(peaks) if peaks else None


def _import_suggest():
    """Load tokdash.suggest (package-relative or installed)."""
    # Package-relative (glance.py is now in src/tokdash/)
    try:
        from .suggest import build_suggest, format_glance_lines
        return build_suggest, format_glance_lines
    except Exception:
        pass
    # Installed package
    try:
        from tokdash.suggest import build_suggest, format_glance_lines
        return build_suggest, format_glance_lines
    except Exception:
        pass
    # Standalone AppData copy: try repo checkout next to scripts/, then common path.
    candidates = [
        Path(__file__).resolve().parent.parent / "src",
        Path(r"K:/Projects/kdash/src"),
        Path.home() / "Projects" / "kdash" / "src",
    ]
    for src in candidates:
        if not (src / "tokdash" / "suggest.py").is_file():
            continue
        sp = str(src)
        if sp not in sys.path:
            sys.path.insert(0, sp)
        try:
            from tokdash.suggest import build_suggest, format_glance_lines
            return build_suggest, format_glance_lines
        except Exception:
            continue
    return None, None


def _zenmux_flows_left(
    records: list[dict[str, Any]],
) -> tuple[float | None, float | None, float | None, float | None]:
    """Parse 5h/7d remaining/max flows from ZenMux meter extras or info rows."""
    rem5 = rem7 = max5 = max7 = None
    for r in records:
        sec = str(r.get("section") or "")
        if not sec.upper().startswith("ZENMUX"):
            continue
        if r.get("kind") == "info" and str(r.get("label") or "").lower().startswith(
            "flows left"
        ):
            # "5h 44/50 · 7d 113/213 · ~N med M3 turns"
            val = str(r.get("value") or "")
            m5 = re.search(r"5h\s+([\d.]+)/([\d.]+)", val)
            m7 = re.search(r"7d\s+([\d.]+)/([\d.]+)", val)
            if m5:
                rem5 = float(m5.group(1))
                max5 = float(m5.group(2))
            if m7:
                rem7 = float(m7.group(1))
                max7 = float(m7.group(2))
        if r.get("kind") == "meter":
            lab = str(r.get("label") or "").lower()
            extra = str(r.get("extra") or "")
            # "113/213 fl left · ..."
            m = re.search(r"([\d.]+)/([\d.]+)\s*fl\s*left", extra)
            if not m:
                continue
            if "5" in lab:
                rem5 = float(m.group(1))
                max5 = float(m.group(2))
            elif "7" in lab:
                rem7 = float(m.group(1))
                max7 = float(m.group(2))
    return rem5, rem7, max5, max7


def _clip_extra_keep_budget(extra: str, limit: int = 36) -> str:
    """Clip meter extra keeping load-bearing tokens: flows left, then reset day.

    Drop ``$x/$y`` first. Prefer ``reset MM-DD`` over truncating mid-date/time.
    At tight widths, shorten ``fl left`` → ``fl`` so the reset day still fits.
    """
    s = (extra or "").strip()
    if not s or len(s) <= limit:
        return s

    m = re.match(r"^(\d+(?:\.\d+)?/\d+(?:\.\d+)?)\s*fl(?:\s*left)?", s)
    rest = s
    ratio = fl_full = fl_short = ""
    if m:
        ratio = m.group(1)
        fl_full = f"{ratio} fl left"
        fl_short = f"{ratio} fl"
        rest = s[m.end() :]

    rm = re.search(
        r"reset\s+(\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?|\d{4}-\d{2}-\d{2}|\?)",
        rest,
        flags=re.I,
    )
    reset_tok = rm.group(1) if rm else ""
    reset_full = f"reset {reset_tok}" if reset_tok else ""
    day_only = ""
    if reset_tok:
        day_m = re.match(r"(\d{2}-\d{2}|\d{4}-\d{2}-\d{2}|\?)", reset_tok)
        if day_m:
            day_only = day_m.group(1)
    reset_day = f"reset {day_only}" if day_only else ""

    dm = re.search(r"(\$[\d.]+/\$[\d.]+)", rest)
    dollar = dm.group(1) if dm else ""

    def join(ps: list[str]) -> str:
        return " · ".join(p for p in ps if p)

    # Richest → leanest. Prefer any flows+reset form over bare flows.
    # Ultra-tight (~13 chars at 80-col board): "112/213·07-18"
    candidates: list[str] = []
    fl_opts = [f for f in (fl_full, fl_short) if f]
    for fl in fl_opts:
        candidates.append(
            join([fl] + ([reset_full] if reset_full else []) + ([dollar] if dollar else []))
        )
        candidates.append(join([fl] + ([reset_full] if reset_full else [])))
        if reset_day and reset_day != reset_full:
            candidates.append(join([fl, reset_day]))
    if ratio and day_only:
        candidates.append(f"{ratio}·{day_only}")
    candidates.extend(fl_opts)
    if reset_day:
        candidates.append(reset_day)
    if reset_full:
        candidates.append(reset_full)
    if day_only:
        candidates.append(day_only)

    for cand in candidates:
        if cand and len(cand) <= limit:
            return cand

    if fl_short and len(fl_short) <= limit:
        return fl_short
    return s[: max(0, limit - 1)] + "…"


def _advice_from_records(records: list[dict[str, Any]]) -> list[str]:
    """Right-rail SUGGEST via shared tokdash.suggest policy (single source)."""
    meters = [r for r in records if r.get("kind") == "meter"]
    warns = [r for r in records if r.get("kind") in ("warn", "err")]
    sections = {
        str(r.get("title") or r.get("section") or "")
        for r in records
        if r.get("kind") == "section"
    }

    def has_sec(prefix: str) -> bool:
        p = prefix.casefold()
        return any(s.casefold().startswith(p) for s in sections)

    zm = _section_peak(records, "ZENMUX")
    cl = _section_peak(records, "CLAUDE")
    cp = _section_peak(records, "CLINEPASS")
    zai = _section_peak(records, "Z.AI")
    qc = _section_peak(records, "QWEN")
    rem5, rem7, max5, max7 = _zenmux_flows_left(records)

    # ZenMux plan end from section subtitle
    zm_end = None
    for r in records:
        if r.get("kind") != "section":
            continue
        if not str(r.get("title") or "").upper().startswith("ZENMUX"):
            continue
        sub = str(r.get("subtitle") or "")
        if "exp " in sub:
            piece = sub.split("exp ", 1)[1][:10]
            if len(piece) == 10 and piece[4] == "-":
                zm_end = piece

    HOT = 85.0
    hot_items: list[str] = []
    for m in meters:
        pct = float(m.get("pct") or 0)
        if pct < HOT:
            continue
        sec = str(m.get("section") or "?").split()[0][:10]
        lab = str(m.get("label") or "")
        hot_items.append(f"{sec} {lab} {pct:.0f}%")
    hot_items.sort(key=lambda s: -float(s.rsplit(" ", 1)[-1].rstrip("%") or 0))

    # Near resets from meter extras
    for m in meters:
        extra = str(m.get("extra") or "")
        reset_dt, token = _parse_reset_hint(extra)
        if reset_dt is None:
            continue
        hours = (reset_dt - datetime.now()).total_seconds() / 3600.0
        if -1 <= hours <= 48:
            sec = str(m.get("section") or "?").split()[0][:10]
            lab = str(m.get("label") or "")
            hot_items.append(f"{sec} {lab} → {token}")

    warn_items = [str(w.get("msg") or "") for w in warns[:3]]

    build_suggest, format_glance_lines = _import_suggest()
    if build_suggest is None or format_glance_lines is None:
        # Minimal fallback if package missing
        lines = ["SUGGEST", "─" * 28, "· tokdash.suggest unavailable"]
        if rem7 is not None:
            lines.insert(2, f"Flows 7d {rem7:.0f} left")
        lines.append("Tip: pip install -e tokdash-fork")
        return lines
    data = build_suggest(
        zenmux_peak_pct=zm,
        claude_peak_pct=cl,
        clinepass_peak_pct=cp,
        zai_peak_pct=zai,
        qwencloud_peak_pct=qc,
        zenmux_rem5=rem5,
        zenmux_rem7=rem7,
        zenmux_max5=max5,
        zenmux_max7=max7,
        has_iamhc=has_sec("IAMHC"),
        has_agnes=has_sec("AGNES"),
        zenmux_end=zm_end,
    )
    return format_glance_lines(
        data, hot_items=hot_items[:4], warn_items=warn_items, width=28
    )


def _compose_left(
    records: list[dict[str, Any]],
    *,
    bar_w: int = 10,
    line_width: int | None = None,
) -> list[str]:
    """Dense meters — no blank gaps between providers.

    ``line_width`` is the visible left-column budget (from compose_dashboard).
    Meter extras expand to fill remaining width instead of a hard 28-char clip.
    """
    lines: list[str] = []
    # " lab123456789  12.0% [##########] " → 1+12+1+6+1+(bar_w+2)+1
    meter_prefix = 1 + 12 + 1 + 6 + 1 + (bar_w + 2) + 1
    info_prefix = 1 + 12 + 1
    default_extra = 40
    i = 0
    while i < len(records):
        r = records[i]
        if r["kind"] == "section":
            title = str(r.get("title") or "")
            sub = str(r.get("subtitle") or "")
            head = bold(title) if USE_COLOR else title
            if sub:
                # Prefer keeping YYYY-MM-DD tokens intact when clipping.
                sub_limit = max(24, (line_width - len(title) - 1) if line_width else 36)
                clipped = sub
                if len(clipped) > sub_limit:
                    clipped = clipped[:sub_limit]
                    # if we cut inside a date, back up to previous separator
                    if clipped[-1].isdigit() and "20" in clipped[-8:]:
                        for sep in (" · ", " ", "·"):
                            idx = clipped.rfind(sep)
                            if idx >= 12:
                                clipped = clipped[:idx]
                                break
                    if len(str(r.get("subtitle") or "")) > len(clipped):
                        clipped = clipped.rstrip(" ·") + "…"
                head = f"{head} {dim(clipped)}"
            lines.append(head)
            i += 1
            while i < len(records) and records[i]["kind"] != "section":
                row = records[i]
                if row["kind"] == "meter":
                    lab = str(row.get("label") or "")[:12]
                    pct = float(row.get("pct") or 0)
                    extra_limit = (
                        max(22, line_width - meter_prefix)
                        if line_width
                        else default_extra
                    )
                    extra = _clip_extra_keep_budget(
                        str(row.get("extra") or ""), limit=extra_limit
                    )
                    lines.append(
                        f" {lab:<12} {fmt_pct(pct)} {bar(pct, bar_w)}"
                        + (f" {dim(extra)}" if extra else "")
                    )
                elif row["kind"] == "info":
                    lab = str(row.get("label") or "")[:12]
                    val = str(row.get("value") or "")
                    val_limit = (
                        max(24, line_width - info_prefix) if line_width else 48
                    )
                    if len(val) > val_limit:
                        # Prefer not cutting inside MM-DD / YYYY-MM-DD
                        cut = val[: val_limit - 1]
                        for sep in (" · ", " ", "·"):
                            idx = cut.rfind(sep)
                            if idx >= 10:
                                cut = cut[:idx]
                                break
                        val = cut.rstrip(" ·") + "…"
                    lines.append(f" {lab:<12} {val}")
                elif row["kind"] == "warn":
                    msg = str(row.get("msg") or "")
                    lines.append(
                        c(_YELLOW, f" ! {msg}") if USE_COLOR else f" ! {msg}"
                    )
                elif row["kind"] == "err":
                    msg = str(row.get("msg") or "")
                    lines.append(c(_RED, f" x {msg}") if USE_COLOR else f" x {msg}")
                elif row["kind"] == "raw":
                    lines.append(str(row.get("text") or ""))
                i += 1
        else:
            if r["kind"] == "raw":
                lines.append(str(r.get("text") or ""))
            i += 1
    return lines


def compose_dashboard(
    records: list[dict[str, Any]],
    *,
    term_cols: int | None = None,
) -> list[str]:
    """Two-column board: left meters, right SUGGEST box."""
    try:
        cols = term_cols or shutil.get_terminal_size(fallback=(100, 30)).columns
    except Exception:
        cols = 100
    cols = max(72, min(cols, 140))

    right_w = 32 if cols < 100 else min(36, max(30, cols // 3))
    gap = 2
    left_w = cols - right_w - gap - 1

    left = _compose_left(
        records,
        bar_w=8 if left_w < 52 else 10,
        line_width=left_w,
    )
    right = _advice_from_records(records)

    inner = right_w - 2
    boxed: list[str] = []
    top = "┌" + "─" * inner + "┐"
    bot = "└" + "─" * inner + "┘"
    edge = c(_CYAN, "│") if USE_COLOR else "│"
    boxed.append(c(_CYAN, top) if USE_COLOR else top)
    for line in right:
        plain = _strip_ansi(line)
        if len(plain) > inner - 1:
            plain = plain[: inner - 2] + "…"
        pad = inner - 1 - len(plain)
        # First line bold title
        if line in ("NEXT / EXPIRING", "SUGGEST") and USE_COLOR:
            body = bold(plain)
            boxed.append(edge + " " + body + (" " * max(0, pad)) + edge)
        elif (
            line.startswith("Use next")
            or line.startswith("NOW:")
            or line.startswith("T0 ")
            or line.startswith("T1 ")
            or line.startswith("T2 ")
        ) and USE_COLOR:
            body = c(_GREEN, plain)
            boxed.append(edge + " " + body + (" " * max(0, pad)) + edge)
        elif (
            line.startswith("T3 ")
            or line.startswith("T4 ")
            or line.startswith("Flows ")
        ) and USE_COLOR:
            body = c(_CYAN, plain)
            boxed.append(edge + " " + body + (" " * max(0, pad)) + edge)
        elif (
            line.startswith("Avoid")
            or line.startswith("Skip")
            or line.startswith("Hot /")
        ) and USE_COLOR:
            body = c(_RED, plain)
            boxed.append(edge + " " + body + (" " * max(0, pad)) + edge)
        elif (
            line.startswith("Deadlines")
            or line.startswith("Expiring")
            or line.startswith("mode:")
        ) and USE_COLOR:
            body = c(_YELLOW, plain)
            boxed.append(edge + " " + body + (" " * max(0, pad)) + edge)
        else:
            boxed.append(edge + " " + plain + (" " * max(0, pad)) + edge)
    boxed.append(c(_CYAN, bot) if USE_COLOR else bot)

    n = max(len(left), len(boxed))
    left += [""] * (n - len(left))
    boxed += [""] * (n - len(boxed))

    out: list[str] = []
    for L, R in zip(left, boxed):
        out.append(_pad_visible(L, left_w) + (" " * gap) + R)
    return out


def render(
    period: str,
    *,
    want_tools: bool,
    sections: dict[str, bool],
    show_cost: bool,
) -> int:
    rc = 0
    order = [
        ("zenmux", "ZENMUX"),
        ("claude", "CLAUDE"),
        ("clinepass", "CLINEPASS"),
        ("zai", "ZAI"),
        ("codex", "CODEX"),
        ("moonshot", "MOONSHOT"),
        ("agnes", "AGNES"),
        ("iamhc", "IAMHC"),
        ("fireworks", "FIREWORKS"),
        ("openrouter", "OPENROUTER"),
        ("deepseek", "DEEPSEEK"),
        ("qwencloud", "QWEN CLOUD"),
    ]
    try:
        from .sources.quota import quota_state

        state = quota_state()
        providers = state.get("providers") or {}
    except Exception as e:
        section("QUOTA", "error")
        err_row(f"quota_state failed: {e}")
        rc = 1
        providers = {}

    for name, label in order:
        if not sections.get(name, True):
            continue
        pdata = providers.get(name)
        if not pdata:
            continue
        status = pdata.get("status") or "?"
        # Skip providers with no data and no buckets
        buckets = pdata.get("buckets") or []
        if status == "unavailable" and not buckets:
            continue

        plan = pdata.get("plan") or ""
        subtitle_parts = [plan] if plan else [status]
        # Show subscription/trial expiry when available
        expiry = None
        for bucket in buckets:
            e = bucket.get("expires_at")
            if e:
                expiry = e
                break
        if expiry:
            try:
                exp_dt = datetime.fromtimestamp(expiry)
                days_left = (exp_dt - datetime.now()).days
                if days_left <= 30:
                    subtitle_parts.append(f"exp {exp_dt.strftime('%m-%d')} ({days_left}d)")
            except Exception:
                pass
        subtitle = " · ".join(subtitle_parts)
        section(label, subtitle)

        for bucket in buckets:
            b_label = bucket.get("bucket_label") or bucket.get("bucket") or "?"
            pct = bucket.get("used_percent")
            resets = bucket.get("resets_at")
            if pct is not None:
                extra_parts = []
                if resets:
                    try:
                        extra_parts.append(
                            f"resets {datetime.fromtimestamp(resets).strftime('%m-%d %H:%M')}"
                        )
                    except Exception:
                        pass
                kv_row(b_label, pct, " · ".join(extra_parts) if extra_parts else "")
            else:
                info_row(b_label, str(bucket.get("status") or ""))
        status_detail = pdata.get("status_detail")
        if status_detail and status not in ("ok", "unavailable"):
            warn_row(str(status_detail))
        if pdata.get("estimated"):
            info_row("note", "may include session data")
        # Warn when subscription expires within 7 days
        if expiry:
            try:
                exp_dt = datetime.fromtimestamp(expiry)
                days_left = (exp_dt - datetime.now()).days
                if 0 <= days_left <= 7:
                    warn_row(f"expires in {days_left}d — {exp_dt.strftime('%Y-%m-%d')}")
                elif days_left < 0:
                    warn_row(f"expired {abs(days_left)}d ago — {exp_dt.strftime('%Y-%m-%d')}")
            except Exception:
                pass
        # Qwen Cloud staleness: Firefox cookies are refreshed by the browser,
        # but the API response is cached. Flag when >5h old (quota window length).
        if name == "qwencloud" and buckets:
            for bucket in buckets:
                if bucket.get("bucket") == "5h":
                    captured = bucket.get("captured_at")
                    if captured:
                        age_h = (int(datetime.now().timestamp()) - captured) / 3600
                        if age_h > 5:
                            info_row("stale", f"5h data {age_h:.0f}h old — restart kdash or wait for next poll")
                    break

    if want_tools:
        rc = glance_tools(period, show_cost=show_cost) or rc
    return rc


def _enable_vt() -> None:
    """Enable VT processing on Windows consoles when possible.
    Windows Terminal processes VT natively, so a failure here is non-fatal —
    but we do try so that cmd.exe / conhost also work.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return  # not a real console — nothing to enable
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x0004) makes VT escape
        # sequences (including alt-screen) work. ENABLE_PROCESSED_OUTPUT
        # (0x0001) makes \n, \r, \b, \t, \a process as expected.
        needed = 0x0004 | 0x0001
        if mode.value & needed == needed:
            return  # already set
        kernel32.SetConsoleMode(handle, mode.value | needed)
    except Exception:
        pass  # non-fatal — Windows Terminal works without it


def header_lines(watch: bool, interval: int) -> list[str]:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = bold("tokdash-glance")
    if watch:
        meta = dim(f"{ts}  ·  every {interval}s  ·  q quit  ·  r refresh  ·  o open web")
    else:
        meta = dim(f"{ts}  ·  web: {TOKDASH}")
    return [
        f"{title}  {meta}",
        dim("─" * 72) if USE_COLOR else "-" * 72,
        "",
    ]


def open_web_dashboard() -> bool:
    """Open the tokdash web GUI in the default browser. Returns True on success.

    Best-effort: a missing/missconfigured browser must never crash the TUI.
    """
    try:
        webbrowser.open(TOKDASH)
        return True
    except Exception:
        return False


def set_terminal_title(title: str) -> None:
    """Set Windows Terminal / conhost tab title via OSC 0."""
    try:
        sys.stdout.write(f"\x1b]0;{title}\x07")
        sys.stdout.flush()
    except Exception:
        pass


def enter_dashboard() -> None:
    """Switch to alternate screen + hide cursor (top/htop style)."""
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[H\x1b[2J")
    sys.stdout.flush()
    set_terminal_title("tokdash-watch")


def leave_dashboard() -> None:
    """Restore main screen + show cursor."""
    sys.stdout.write("\x1b[?25h\x1b[?1049l")
    sys.stdout.flush()

def paint_frame(lines: list[str]) -> None:
    """Redraw the alt-screen in place: home, write lines, erase remainder.
    Reads terminal size each call to handle resize.

    Important: the last line must NOT have a trailing \r\n — that would
    scroll the alt-screen buffer when the frame fills the terminal height.
    """
    try:
        size = shutil.get_terminal_size(fallback=(80, 28))
        rows = max(8, size.lines)
    except Exception:
        rows = 28
    # Leave one row spare; clamp frame height so we never scroll the alt buffer.
    budget = max(4, rows - 1)
    visible = lines[:budget]
    if len(lines) > budget:
        visible = lines[: budget - 1] + [
            dim(f"  … {len(lines) - budget + 1} more lines (resize terminal)")
        ]
    parts: list[str] = ["\x1b[H"]  # cursor home
    n = len(visible)
    for i, line in enumerate(visible):
        # \x1b[2K clears the entire line, \r homes to column 0.
        parts.append("\x1b[2K\r")
        parts.append(line)
        if i < n - 1:
            # \r\n advances to the next line start (not the last line).
            parts.append("\r\n")
        # Last line: no trailing newline — cursor stays on this line,
        # \x1b[J below clears everything from here to end of screen.
    parts.append("\x1b[J")  # clear from last content line to end of screen
    sys.stdout.write("".join(parts))
    sys.stdout.flush()


def build_frame(
    period: str,
    *,
    want_tools: bool,
    sections: dict[str, bool],
    show_cost: bool,
    watch: bool,
    interval: int,
    compact: bool = True,
) -> tuple[list[str], int]:
    """Collect a full dashboard frame without painting.

    compact=True (default): two-column board — dense meters left, next/expiring right.
    """
    global _FRAME, _COMPACT, _RECORDS, _CUR_SECTION
    _FRAME = []
    _RECORDS = []
    _CUR_SECTION = ""
    _COMPACT = compact
    try:
        was = _COMPACT
        _COMPACT = False
        for line in header_lines(watch, interval):
            _emit(line)
        _COMPACT = was

        rc = render(
            period,
            want_tools=want_tools,
            sections=sections,
            show_cost=show_cost,
        )
        if compact:
            body = compose_dashboard(list(_RECORDS))
            for line in body:
                if _FRAME is not None:
                    _FRAME.append(line)
                else:
                    print(line)
        return list(_FRAME or []), rc
    finally:
        _FRAME = None
        _COMPACT = False
        _RECORDS = []
        _CUR_SECTION = ""


def _poll_key() -> str | None:
    """Non-blocking single key if available (Windows msvcrt / POSIX tty)."""
    try:
        if os.name == "nt":
            import msvcrt

            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0") and msvcrt.kbhit():
                    msvcrt.getwch()  # swallow special-key trail
                    return None
                return ch
            return None
        import select

        if not sys.stdin.isatty():
            return None
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if r:
            return sys.stdin.read(1)
    except Exception:
        return None
    return None


def loading_frame(
    period: str,
    *,
    sections: dict[str, bool],
    want_tools: bool,
    watch: bool,
    interval: int,
    note: str = "Loading…",
) -> list[str]:
    """Immediate first paint so the alt-screen is never a blank black void."""
    lines = list(header_lines(watch, interval))
    lines.append(bold(note) if USE_COLOR else note)
    lines.append(dim(f"  period={period}  ·  {TOKDASH}"))
    names = [name for name, on in sections.items() if on]
    if want_tools:
        names.append("tools")
    if names:
        lines.append(dim("  fetching: ") + " ".join(names))
    else:
        lines.append(dim("  (no sections enabled)"))
    lines.append(dim("  keys: q quit · r/space refresh now"))
    return lines


def watch_loop(
    period: str,
    *,
    want_tools: bool,
    sections: dict[str, bool],
    show_cost: bool,
    interval: int,
    compact: bool = True,
) -> int:
    """top-like dashboard: splash immediately, then fetch + paint in place."""
    _enable_vt()
    enter_dashboard()
    # Never leave the user staring at an empty alt-buffer while HTTP runs.
    paint_frame(
        loading_frame(
            period,
            sections=sections,
            want_tools=want_tools,
            watch=True,
            interval=interval,
            note="Loading providers…",
        )
    )
    rc = 0
    last_lines: list[str] | None = None
    try:
        while True:
            # Keep last good frame visible while fetching (no black wipe).
            if last_lines:
                busy = list(last_lines)
                if busy and "refresh" in _strip_ansi(busy[-1]).lower():
                    busy[-1] = dim(
                        f"  refreshing… · keys: q quit · r/space refresh · o open web · {TOKDASH}"
                    )
                else:
                    busy.append("")
                    busy.append(
                        dim(
                            f"  refreshing… · keys: q quit · r/space refresh · o open web · {TOKDASH}"
                        )
                    )
                paint_frame(busy)

            lines, rc = build_frame(
                period,
                want_tools=want_tools,
                sections=sections,
                show_cost=show_cost,
                watch=True,
                interval=interval,
                compact=compact,
            )
            lines.append("")
            lines.append(
                dim(
                    f"  refresh {interval}s · keys: q quit · r/space refresh now · o open web · data from {TOKDASH}"
                )
            )
            last_lines = list(lines)
            paint_frame(lines)
            set_terminal_title(
                f"tokdash-watch · {datetime.now().strftime('%H:%M:%S')}"
            )

            # Sleep in small slices so q/r are responsive
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline:
                key = _poll_key()
                if key:
                    k = key.lower()
                    if k in {"q", "\x03"}:  # q or Ctrl+C char
                        return rc
                    if k in {"r", " "}:
                        break  # immediate refresh
                    if k == "o":
                        # Open the web GUI; keep the TUI running.
                        open_web_dashboard()
                time.sleep(0.1)
    except KeyboardInterrupt:
        return rc
    finally:
        leave_dashboard()
        print(dim("(tokdash-watch stopped)"))


def main(argv: list) -> int:
    if USE_COLOR:
        _enable_vt()

    args = [a for a in argv if a]
    period = PERIOD
    want_tools = True
    show_cost = os.environ.get("TOKDASH_GLANCE_SHOW_COST", "").strip() in {
        "1",
        "true",
        "yes",
    }
    watch = False
    interval = DEFAULT_WATCH_S
    compact = True
    sections = {
        "zenmux": True,
        "claude": True,
        "clinepass": True,
        "zai": True,
        "codex": True,
        "moonshot": True,
        "agnes": True,
        "iamhc": True,
        "fireworks": True,
        "openrouter": True,
        "deepseek": True,
    }

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-h", "--help"):
            print("tokdash-glance [period] [options]")
            print("  -w/--watch [--interval N]   top-like dashboard (alt-screen)")
            print("  --cost  --tools-only  --no-tools  --no-<provider>")
            print("  --only-<provider>")
            print(
                "  providers: zenmux claude clinepass zai codex moonshot "
                "agnes iamhc fireworks openrouter deepseek"
            )
            print("  watch keys: q quit · r/space refresh now")
            print("  --classic  single-column (no SUGGEST rail)")
            print("  TOKDASH_GLANCE_NO_COLOR=1 to disable colors")
            return 0
        if a in ("-w", "--watch", "--persist", "--persistent"):
            watch = True
            i += 1
            continue
        if a in ("--interval", "-n") and i + 1 < len(args):
            interval = max(5, int(args[i + 1]))
            i += 2
            continue
        if a.startswith("--interval="):
            interval = max(5, int(a.split("=", 1)[1]))
            i += 1
            continue
        if a == "--period" and i + 1 < len(args):
            period = args[i + 1]
            i += 2
            continue
        if a.startswith("--period="):
            period = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--cost":
            show_cost = True
            i += 1
            continue
        if a == "--classic":
            compact = False
            i += 1
            continue
        if a == "--tools-only":
            for k in sections:
                sections[k] = False
            want_tools = True
            i += 1
            continue
        if a == "--no-tools":
            want_tools = False
            i += 1
            continue
        if a.startswith("--no-") and a[5:] in sections:
            sections[a[5:]] = False
            i += 1
            continue
        if a.startswith("--only-") and a[7:] in sections:
            for k in sections:
                sections[k] = k == a[7:]
            want_tools = False
            i += 1
            continue
        if a in ("today", "week", "month", "3days", "14days") or a.isdigit():
            period = a
            i += 1
            continue
        print(f"unknown arg: {a}", file=sys.stderr)
        return 2

    if watch:
        return watch_loop(
            period,
            want_tools=want_tools,
            sections=sections,
            show_cost=show_cost,
            interval=interval,
            compact=compact,
        )

    # One-shot: print to normal terminal (no alt-screen)
    lines, rc = build_frame(
        period,
        want_tools=want_tools,
        sections=sections,
        show_cost=show_cost,
        watch=False,
        interval=interval,
        compact=compact,
    )
    for line in lines:
        print(line)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
