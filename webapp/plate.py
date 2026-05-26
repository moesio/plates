import re

from webapp import config as cfg

_PLATE_RE = None
_PLATE_PATTERN = None


def _get_plate_re():
    global _PLATE_RE, _PLATE_PATTERN
    pattern = cfg.get("plate_regex", "^[A-Z]{3}(?:\\d{4}|\\d[A-Z]\\d{2})$")
    if pattern != _PLATE_PATTERN:
        _PLATE_RE = re.compile(pattern)
        _PLATE_PATTERN = pattern
    return _PLATE_RE


def _is_valid_plate(text):
    return bool(_get_plate_re().match(text.upper().replace("-", "").strip()))
