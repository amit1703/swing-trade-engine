# indicators package
#
# Re-export all functions from the sibling indicators.py module so that
# `from indicators import ema, sma, cci, atr` continues to work after the
# indicators/ package directory was created alongside indicators.py.

import importlib.util
import os as _os

_module_file = _os.path.join(_os.path.dirname(__file__), "..", "indicators.py")
_spec = importlib.util.spec_from_file_location("_indicators_impl", _module_file)
_impl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_impl)

ema = _impl.ema
sma = _impl.sma
atr = _impl.atr
cci = _impl.cci
true_range = _impl.true_range
