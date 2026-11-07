"""Backward-compatible import alias; preserves older callers and monkeypatches."""
import sys
from modules.notebook import legacy_notebook as _implementation
sys.modules[__name__] = _implementation
