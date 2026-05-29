import logging
import threading
import time

from webapp import config as cfg

logger = logging.getLogger(__name__)

_STALE_MULTIPLIER = 2
_seen = {}
_seen_lock = threading.Lock()
_save_counter = 0


def _check_dedup(plate_text, cam_id):
    now = time.time()
    key = (plate_text, cam_id)
    window = cfg.get_int("dedup_seconds", 60)
    with _seen_lock:
        last = _seen.get(key)
        if last is not None and now - last < window:
            return False
        _seen[key] = now
        return True


def _cleanup_stale():
    now = time.time()
    window = cfg.get_int("dedup_seconds", 60)
    cutoff = now - window * _STALE_MULTIPLIER
    with _seen_lock:
        stale = [k for k, t in _seen.items() if t < cutoff]
        for k in stale:
            del _seen[k]
    if stale:
        logger.debug("Purged %d stale dedup entries", len(stale))
