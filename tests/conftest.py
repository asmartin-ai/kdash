from __future__ import annotations

import os
import pytest

# Prevent browser opens during the entire test run.  tokdash's _has_display()
# reads CI (returns False if set) and on Windows default-assumes a GUI is
# present.  Setting CI=true at module-load time (before any test imports) stops
# every webbrowser.open() timer from ever firing.
os.environ["CI"] = "true"


@pytest.fixture(autouse=True)
def isolated_usage_db(monkeypatch, tmp_path):
    """Keep the default-on persistent usage DB isolated per test.

    The runtime default is intentionally controlled by application code, but
    tests must not share ~/.tokdash/usage.sqlite3 or one test's cached rows can
    leak into another source fixture.
    """
    data_dir = tmp_path / ".tokdash-test"
    monkeypatch.setenv("TOKDASH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("TOKDASH_USAGE_DB_PATH", str(data_dir / "usage.sqlite3"))
