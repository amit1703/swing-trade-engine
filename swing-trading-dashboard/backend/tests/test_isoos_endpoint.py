import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_isoos_run_request_defaults():
    """ISOOSRunRequest has correct default values."""
    import main as m
    req = m.ISOOSRunRequest()
    assert req.is_start_date == "2017-01-01"
    assert req.is_end_date == "2021-12-31"
    assert req.oos_start_date == "2022-01-01"
    assert req.oos_end_date == "2024-12-31"
    assert req.max_positions == 4
    assert req.ticker_count is None
    assert req.min_score == 0.0
    assert "PULLBACK" in req.setup_types
    assert "VCP" not in req.setup_types


def test_isoos_status_initial_state():
    """_isoos_status global starts idle."""
    import main as m
    m._isoos_status.update({
        "status": "idle", "is_done": False,
        "current": 0, "total": 0, "phase": None, "error": None,
    })
    assert m._isoos_status["status"] == "idle"
    assert m._isoos_status["is_done"] is False
    assert m._isoos_status["phase"] is None
    assert m._isoos_status["error"] is None


def test_isoos_cache_path_is_in_cache_dir():
    """ISOOS_DIAG_CACHE_PATH resolves inside the cache/ directory."""
    import main as m
    assert "isoos_diagnostics.json" in m.ISOOS_DIAG_CACHE_PATH
    assert "cache" in m.ISOOS_DIAG_CACHE_PATH.replace("\\", "/")
