"""Backward-compatible import alias; implementation is owned by notebook module."""
import sys
from modules.notebook import legacy_store as _implementation
sys.modules[__name__] = _implementation
