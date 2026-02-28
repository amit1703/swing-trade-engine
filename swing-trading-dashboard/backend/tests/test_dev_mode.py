import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient
import main as m
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_scan_state():
    """Ensure each test starts with scan not in progress."""
    m._scan_state["in_progress"] = False
    yield
    m._scan_state["in_progress"] = False


def test_scan_status_has_engine_stats():
    """scan-status response must include engine_stats key with all required sub-keys."""
    resp = client.get("/api/scan-status")
    assert resp.status_code == 200
    data = resp.json()
    assert "engine_stats" in data
    stats = data["engine_stats"]
    for key in ("e0", "e1", "e2", "e3", "e5", "e6", "forced", "dry_run"):
        assert key in stats, f"Missing engine_stats.{key}"


def test_engine_stats_key_types():
    """engine_stats values must have correct types."""
    resp = client.get("/api/scan-status")
    stats = resp.json()["engine_stats"]
    assert isinstance(stats["e2"]["vcp"], int)
    assert isinstance(stats["e2"]["watchlist"], int)
    assert isinstance(stats["e3"]["pullback"], int)
    assert isinstance(stats["e3"]["relaxed"], int)
    assert isinstance(stats["total_tickers"], int)
    assert isinstance(stats["total_duration_s"], float)
    assert isinstance(stats["forced"], bool)
    assert isinstance(stats["dry_run"], bool)


def test_trigger_scan_accepts_force_param():
    """POST /api/run-scan?force=true must return 200 (not 422)."""
    resp = client.post("/api/run-scan?force=true")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("started", "already_running")


def test_trigger_scan_accepts_dry_run_param():
    """POST /api/run-scan?dry_run=true must return 200 (not 422)."""
    resp = client.post("/api/run-scan?dry_run=true")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("started", "already_running")


def test_force_and_dry_run_passed_to_run_scan(monkeypatch):
    """force=True and dry_run=True must be forwarded to _run_scan()."""
    captured = {}
    original = m._run_scan

    async def mock_run_scan(scan_ts, tickers, force=False, dry_run=False):
        captured["force"] = force
        captured["dry_run"] = dry_run

    monkeypatch.setattr(m, "_run_scan", mock_run_scan)

    resp = client.post("/api/run-scan?force=true&dry_run=true")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"

    import time
    time.sleep(0.3)

    assert captured.get("force") is True, "force=True was not passed to _run_scan"
    assert captured.get("dry_run") is True, "dry_run=True was not passed to _run_scan"


def test_dry_run_skips_save_scan_run(monkeypatch):
    """dry_run=True must not call save_scan_run (no DB writes)."""
    save_calls = []

    async def mock_save_scan_run(db_path, scan_ts):
        save_calls.append(scan_ts)

    async def mock_run_scan(scan_ts, tickers, force=False, dry_run=False):
        if not dry_run:
            await mock_save_scan_run("db", scan_ts)

    monkeypatch.setattr(m, "_run_scan", mock_run_scan)

    resp = client.post("/api/run-scan?dry_run=true")
    assert resp.status_code == 200

    import time
    time.sleep(0.3)

    assert save_calls == [], f"save_scan_run called {len(save_calls)} time(s) in dry_run mode"
