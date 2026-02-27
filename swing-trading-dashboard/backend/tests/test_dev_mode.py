import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient
from main import app, _scan_state

client = TestClient(app)


def test_scan_status_has_engine_stats():
    """scan-status response must include engine_stats key."""
    resp = client.get("/api/scan-status")
    assert resp.status_code == 200
    data = resp.json()
    assert "engine_stats" in data
    stats = data["engine_stats"]
    for key in ("e0", "e1", "e2", "e3", "e5", "e6", "forced", "dry_run"):
        assert key in stats, f"Missing engine_stats.{key}"


def test_trigger_scan_accepts_force_param():
    """POST /api/run-scan?force=true must be accepted (not 422)."""
    resp = client.post("/api/run-scan?force=true")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("started", "already_running")


def test_trigger_scan_accepts_dry_run_param():
    """POST /api/run-scan?dry_run=true must be accepted."""
    resp = client.post("/api/run-scan?dry_run=true")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("started", "already_running")
