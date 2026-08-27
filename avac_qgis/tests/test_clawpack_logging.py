"""Regression for cwd-independent suppression of PyClaw's import config."""

from __future__ import annotations

import logging.config
import os

from avac_qgis.core.clawpack_logging import suppress_pyclaw_file_logging


def main() -> None:
    original = logging.config.fileConfig
    calls: list[object] = []

    def fake_file_config(config, *args, **kwargs):
        calls.append(config)

    old_cwd = os.getcwd()
    logging.config.fileConfig = fake_file_config
    try:
        os.chdir("/")
        with suppress_pyclaw_file_logging():
            logging.config.fileConfig("/bundled/clawpack-src/pyclaw/src/pyclaw/log.config")
            logging.config.fileConfig("/another/plugin/log.config")
        assert calls == ["/another/plugin/log.config"]
        assert logging.config.fileConfig is fake_file_config
    finally:
        os.chdir(old_cwd)
        logging.config.fileConfig = original
    print("PyClaw result logging suppression/restoration is cwd-independent: PASS")


if __name__ == "__main__":
    main()
