"""Tests for macro_service.py — run with: pytest backend/tests/test_macro_service.py -v"""
import time
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_market_overview_returns_required_keys():
    """get_market_overview() always returns the four top-level keys."""
    import services.macro_service as svc

    svc._cache    = None
    svc._cache_ts = 0.0

    with patch.object(svc, "_fetch_fear_greed",   new=AsyncMock(return_value={"score": 42.0, "label": "Fear"})):
        with patch.object(svc, "_fetch_index_change", new=AsyncMock(return_value={"price": 500.0, "change_pct": -1.0})):
            with patch.object(svc, "_fetch_news",     new=AsyncMock(return_value=[])):
                result = await svc.get_market_overview()

    for key in ("fear_greed", "indices", "news", "cached_at", "cache_age_s"):
        assert key in result, f"Missing key: {key}"
    assert result["fear_greed"]["score"] == 42.0
    assert "SPY" in result["indices"]
    assert "QQQ" in result["indices"]


@pytest.mark.asyncio
async def test_get_market_overview_uses_cache_on_second_call():
    """Second call within TTL must return cached data without re-fetching."""
    import services.macro_service as svc

    svc._cache = {
        "fear_greed": {"score": 99.0, "label": "Extreme Greed"},
        "indices": {"SPY": None, "QQQ": None},
        "news": [],
        "cached_at": "2026-01-01T00:00:00",
        "cache_age_s": 0,
    }
    svc._cache_ts = time.monotonic()  # fresh

    call_count = 0
    original   = svc._fetch_fear_greed

    async def _counting_mock():
        nonlocal call_count
        call_count += 1
        return None

    svc._fetch_fear_greed = _counting_mock
    try:
        await svc.get_market_overview()
        assert call_count == 0, "Cache should have been used — fetch should not have been called"
    finally:
        svc._fetch_fear_greed = original


@pytest.mark.asyncio
async def test_fear_greed_failure_yields_none_not_exception():
    """If CNN endpoint fails, fear_greed is None but function still returns."""
    import services.macro_service as svc

    svc._cache    = None
    svc._cache_ts = 0.0

    with patch.object(svc, "_fetch_fear_greed",   new=AsyncMock(return_value=None)):
        with patch.object(svc, "_fetch_index_change", new=AsyncMock(return_value=None)):
            with patch.object(svc, "_fetch_news",     new=AsyncMock(return_value=[])):
                result = await svc.get_market_overview()

    assert result["fear_greed"] is None
    assert result["indices"]["SPY"] is None
    assert isinstance(result["news"], list)
