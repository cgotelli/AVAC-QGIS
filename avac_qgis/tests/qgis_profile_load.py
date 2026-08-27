"""Verify that AVAC is discoverable from QGIS's normal default profile."""

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.utils import loadPlugin, plugins, startPlugin


def check() -> None:
    QSettings().setValue("/PythonPlugins/avac_qgis", True)
    discovered = "avac_qgis" in plugins or loadPlugin("avac_qgis")
    if discovered and "avac_qgis" not in plugins:
        startPlugin("avac_qgis")
    plugin = plugins.get("avac_qgis")
    if plugin:
        plugin.show_dock()
    print(f"QGIS_PROFILE_DISCOVERED={discovered}", flush=True)
    print(f"QGIS_PROFILE_DOCK_CREATED={bool(plugin and plugin.dock)}", flush=True)
    QCoreApplication.quit()


QTimer.singleShot(1000, check)
