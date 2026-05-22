import threading
import time

from webapp import database

_CACHE = None
_CACHE_TTL = 10
_CACHE_TIME = 0
_LOCK = threading.Lock()

_DEFAULTS = {
    "dedup_seconds": ("60", "Janela de deduplicação em segundos"),
    "cleanup_interval": ("20", "Frequência de limpeza do cache (a cada N saves)"),
    "confidence_threshold": ("0.0", "Confiança mínima para aceitar uma detecção"),
}


def _load():
    global _CACHE, _CACHE_TIME
    raw = dict(_DEFAULTS)
    try:
        session = database.get_session()
        rows = session.query(database.Config).all()
        for row in rows:
            raw[row.key] = (row.value, row.description or "")
        session.close()
    except Exception:
        pass
    _CACHE = raw
    _CACHE_TIME = time.time()


def get(key, default=None):
    now = time.time()
    if _CACHE is None or now - _CACHE_TIME > _CACHE_TTL:
        with _LOCK:
            if _CACHE is None or now - _CACHE_TIME > _CACHE_TTL:
                _load()
    entry = _CACHE.get(key)
    if entry is None:
        return default
    return entry[0]


def get_int(key, default=0):
    try:
        return int(get(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_float(key, default=0.0):
    try:
        return float(get(key, str(default)))
    except (ValueError, TypeError):
        return default


def reload():
    with _LOCK:
        _load()


def seed(session):
    for key, (value, description) in _DEFAULTS.items():
        existing = session.query(database.Config).filter_by(key=key).first()
        if existing is None:
            session.add(database.Config(key=key, value=value, description=description))
    session.commit()
