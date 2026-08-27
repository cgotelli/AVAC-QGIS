"""AVAC QGIS plugin package."""


def classFactory(iface):  # noqa: N802 - QGIS plugin API spelling
    """Return the QGIS plugin instance."""
    from .plugin import AvacQgisPlugin

    return AvacQgisPlugin(iface)
