"""Deprecated alias of :mod:`pii_guard.languages.hu.rules`, kept for one release.

The rules moved into the Hungarian language pack (ADR 0010). This module *is* that module
(the same object in ``sys.modules``), so imports and monkeypatching keep working.
"""

import sys

from pii_guard.languages.hu import rules as _rules

sys.modules[__name__] = _rules
