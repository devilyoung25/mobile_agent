"""Alias of :mod:`on_core.sandbox_state` (module identity preserved for patching)."""

import sys

from on_core import sandbox_state as _mod

sys.modules[__name__] = _mod
