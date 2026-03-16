"""Tests for _apply_tp_multiple helper in main.py."""
import ast
import pathlib
import pytest


def _load_helper():
    """Import only the _apply_tp_multiple function from main.py without running the app."""
    src = pathlib.Path(__file__).parent.parent / "main.py"
    tree = ast.parse(src.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_tp_multiple":
            mod = ast.Module(body=[node], type_ignores=[])
            code = compile(mod, str(src), "exec")
            ns = {}
            exec(code, ns)
            return ns["_apply_tp_multiple"]
    raise ImportError("_apply_tp_multiple not found in main.py")


class FakeParams:
    tp_multiple = 4.3458


def test_tp_override_basic():
    """take_profit = entry + tp_multiple * (entry - stop_loss)."""
    fn = _load_helper()
    signal = {"entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "rr": 2.0}
    result = fn(signal, FakeParams())
    expected_tp = round(100.0 + 4.3458 * 5.0, 2)  # 121.73
    assert result["take_profit"] == expected_tp
    assert result["rr"] == round(4.3458, 3)


def test_tp_override_modifies_in_place():
    """Helper modifies the dict in place AND returns it."""
    fn = _load_helper()
    signal = {"entry": 50.0, "stop_loss": 48.0, "take_profit": 54.0, "rr": 2.0}
    returned = fn(signal, FakeParams())
    assert returned is signal


def test_tp_override_skips_invalid_entry():
    """If entry <= 0, signal is returned unchanged."""
    fn = _load_helper()
    signal = {"entry": 0.0, "stop_loss": 0.0, "take_profit": 0.0, "rr": 0.0}
    result = fn(signal, FakeParams())
    assert result["take_profit"] == 0.0


def test_tp_override_skips_inverted_levels():
    """If stop_loss >= entry (broken signal), signal is returned unchanged."""
    fn = _load_helper()
    signal = {"entry": 95.0, "stop_loss": 100.0, "take_profit": 110.0, "rr": 2.0}
    result = fn(signal, FakeParams())
    assert result["take_profit"] == 110.0  # unchanged


def test_tp_override_fallback_when_no_tp_multiple():
    """Falls back to tp_multiple=2.0 when params has no tp_multiple attribute."""
    fn = _load_helper()

    class MinimalParams:
        pass

    signal = {"entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "rr": 2.0}
    result = fn(signal, MinimalParams())
    expected_tp = round(100.0 + 2.0 * 5.0, 2)  # 110.0
    assert result["take_profit"] == expected_tp
    assert result["rr"] == 2.0
