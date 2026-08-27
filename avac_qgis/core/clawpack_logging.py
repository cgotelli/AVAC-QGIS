"""Scoped suppression of PyClaw's cwd-relative import-time file logger."""

from __future__ import annotations

from contextlib import contextmanager
import logging.config
from pathlib import Path
from threading import RLock
from typing import Iterator


_CONFIG_LOCK = RLock()


def _is_pyclaw_log_config(path: object) -> bool:
    """Recognize only Clawpack's bundled ``pyclaw/log.config`` file."""
    try:
        candidate = Path(path).resolve()
    except (TypeError, OSError):
        return False
    return candidate.name == "log.config" and candidate.parent.name == "pyclaw"


@contextmanager
def suppress_pyclaw_file_logging() -> Iterator[None]:
    """Block only PyClaw's import-time fileConfig call for result reading.

    Clawpack 5.14's ``pyclaw.__init__`` configures ``FileHandler('pyclaw.log')``
    relative to the process cwd and also changes root logging. Results decoding
    neither needs PyClaw logging nor may it write in QGIS's cwd. The original
    ``fileConfig`` function is restored unconditionally; no logger/handler
    owned by QGIS or another plugin is removed or reconfigured.
    """
    with _CONFIG_LOCK:
        original = logging.config.fileConfig

        def result_read_file_config(config, *args, **kwargs):
            if _is_pyclaw_log_config(config):
                return None
            return original(config, *args, **kwargs)

        logging.config.fileConfig = result_read_file_config
        try:
            yield
        finally:
            logging.config.fileConfig = original
