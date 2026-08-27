"""QGIS plugin entry point for AVAC."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtWidgets import QAction

from .gui.dock import AvacDockWidget


class AvacQgisPlugin:
    """Install and remove the AVAC dock and menu action."""

    def __init__(self, iface) -> None:
        self.iface = iface
        self.action: QAction | None = None
        self.help_action: QAction | None = None
        self.documentation_action: QAction | None = None
        self.website_action: QAction | None = None
        self.dock: AvacDockWidget | None = None

    def initGui(self) -> None:  # noqa: N802 - QGIS plugin API spelling
        self.action = QAction(QIcon(), "AVAC4QGIS", self.iface.mainWindow())
        self.action.setObjectName("avacQgisAction")
        self.action.triggered.connect(self.show_dock)
        self.iface.addPluginToMenu("&AVAC4QGIS", self.action)
        self.help_action = QAction("Help", self.iface.mainWindow())
        self.help_action.triggered.connect(self.open_help)
        self.documentation_action = QAction("Online documentation (coming soon)", self.iface.mainWindow()); self.documentation_action.setEnabled(False)
        self.website_action = QAction("AVAC4QGIS website (coming soon)", self.iface.mainWindow()); self.website_action.setEnabled(False)
        for action in (self.help_action, self.documentation_action, self.website_action):
            self.iface.addPluginToMenu("&AVAC4QGIS", action)
        self.iface.addToolBarIcon(self.action)

    def unload(self) -> None:
        if self.dock is not None:
            self.dock.shutdown()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action is not None:
            self.iface.removePluginMenu("&AVAC4QGIS", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        for attribute in ("help_action", "documentation_action", "website_action"):
            action = getattr(self, attribute)
            if action is not None:
                self.iface.removePluginMenu("&AVAC4QGIS", action)
                action.deleteLater()
                setattr(self, attribute, None)

    def open_help(self) -> None:
        if self.dock is not None:
            self.dock.open_help_pdf()
            return
        path = AvacDockWidget.help_pdf_path()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def show_dock(self) -> None:
        if self.dock is None:
            self.dock = AvacDockWidget(self.iface.mainWindow(), self.iface)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()
