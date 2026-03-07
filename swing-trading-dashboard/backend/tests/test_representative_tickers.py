"""Tests for representative_tickers basket."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))


def test_basket_exists_and_is_list():
    from representative_tickers import REPRESENTATIVE_TICKERS
    assert isinstance(REPRESENTATIVE_TICKERS, list)


def test_basket_has_no_duplicates():
    from representative_tickers import REPRESENTATIVE_TICKERS
    assert len(REPRESENTATIVE_TICKERS) == len(set(REPRESENTATIVE_TICKERS))


def test_basket_has_at_least_30_tickers():
    from representative_tickers import REPRESENTATIVE_TICKERS
    assert len(REPRESENTATIVE_TICKERS) >= 30


def test_basket_has_at_most_40_tickers():
    from representative_tickers import REPRESENTATIVE_TICKERS
    assert len(REPRESENTATIVE_TICKERS) <= 40


def test_all_tickers_are_non_empty_strings():
    from representative_tickers import REPRESENTATIVE_TICKERS
    for t in REPRESENTATIVE_TICKERS:
        assert isinstance(t, str) and len(t) > 0


def test_basket_includes_key_tickers():
    """Spot-check: must include large-caps and sector representatives."""
    from representative_tickers import REPRESENTATIVE_TICKERS
    for must_have in ["AAPL", "MSFT", "NVDA", "JPM", "XOM"]:
        assert must_have in REPRESENTATIVE_TICKERS, f"{must_have} missing from basket"
