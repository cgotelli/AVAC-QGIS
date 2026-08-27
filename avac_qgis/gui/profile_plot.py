"""Small Qt-native profile plot, avoiding an additional plotting dependency."""

from __future__ import annotations

import math

import numpy as np
from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from qgis.PyQt.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

from ..core.profiles import ProfileDataset


class ProfilePlotWidget(QWidget):
    def __init__(self, dataset: ProfileDataset, parent=None) -> None:
        super().__init__(parent)
        self.dataset = dataset
        self.setMinimumSize(620, 340)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.white)
        left, right, top, bottom = 70, 24, 30, 55
        plot = self.rect().adjusted(left, top, -right, -bottom)
        painter.setPen(QPen(Qt.black, 1))
        painter.drawLine(plot.bottomLeft(), plot.bottomRight())
        painter.drawLine(plot.bottomLeft(), plot.topLeft())
        x, values = self.dataset.distance_m, self.dataset.values
        valid = np.isfinite(x) & np.isfinite(values)
        if np.any(valid):
            xmin, xmax = float(np.nanmin(x[valid])), float(np.nanmax(x[valid]))
            ymin, ymax = float(np.nanmin(values[valid])), float(np.nanmax(values[valid]))
            if math.isclose(xmin, xmax):
                xmax = xmin + 1.0
            if math.isclose(ymin, ymax):
                pad = max(abs(ymin) * 0.05, 1.0)
                ymin, ymax = ymin - pad, ymax + pad
            path = QPainterPath()
            open_segment = False
            for distance, value in zip(x, values):
                if not (np.isfinite(distance) and np.isfinite(value)):
                    open_segment = False
                    continue
                px = plot.left() + (float(distance) - xmin) / (xmax - xmin) * plot.width()
                py = plot.bottom() - (float(value) - ymin) / (ymax - ymin) * plot.height()
                if open_segment:
                    path.lineTo(QPointF(px, py))
                else:
                    path.moveTo(QPointF(px, py))
                    open_segment = True
            painter.setPen(QPen(QColor(30, 90, 180), 1.5))
            painter.drawPath(path)
            painter.setPen(QPen(Qt.black, 1))
            painter.drawText(4, plot.top() + 10, f"{ymax:.4g}")
            painter.drawText(4, plot.bottom(), f"{ymin:.4g}")
            painter.drawText(plot.right() - 70, plot.bottom() + 20, f"{xmax:.4g} m")
        painter.drawText(plot.center().x() - 100, self.height() - 12, "Distance along profile [m]")
        painter.save()
        painter.translate(16, plot.center().y() + 65)
        painter.rotate(-90)
        painter.drawText(0, 0, f"{self.dataset.variable.title()} [{self.dataset.unit}]")
        painter.restore()


class ProfilePlotDialog(QDialog):
    def __init__(self, dataset: ProfileDataset, parent=None) -> None:
        label = f" — {dataset.profile_name}"
        if dataset.simulation_time_s is not None:
            label += f" at {dataset.simulation_time_s:g} s"
        super().__init__(parent)
        self.setWindowTitle(f"AVAC {dataset.variable.title()} Profile{label}")
        layout = QVBoxLayout(self)
        layout.addWidget(ProfilePlotWidget(dataset, self))


def write_profile_png(path, dataset: ProfileDataset, width: int = 1200) -> None:
    """Write a regular AVAC profile figure without requiring Matplotlib."""
    width = max(320, int(width))
    height = max(260, round(width * 0.55))
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.white)
    widget = ProfilePlotWidget(dataset)
    widget.resize(width, height)
    painter = QPainter(image)
    widget.render(painter)
    painter.end()
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not write profile PNG: {path}")


class TimeSeriesPlotWidget(QWidget):
    """A compact Qt-only plot for Wave gauges and diagnostic histories."""

    def __init__(self, times, values, value_label: str, unit: str, parent=None) -> None:
        super().__init__(parent)
        self.times, self.values = np.asarray(times, float), np.asarray(values, float)
        self.value_label, self.unit = value_label, unit
        self.setMinimumSize(620, 340)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self); painter.fillRect(self.rect(), Qt.white)
        plot = self.rect().adjusted(70, 24, -24, -55)
        painter.setPen(QPen(Qt.black, 1)); painter.drawLine(plot.bottomLeft(), plot.bottomRight()); painter.drawLine(plot.bottomLeft(), plot.topLeft())
        valid = np.isfinite(self.times) & np.isfinite(self.values)
        if np.any(valid):
            xmin, xmax = float(np.nanmin(self.times[valid])), float(np.nanmax(self.times[valid]))
            ymin, ymax = float(np.nanmin(self.values[valid])), float(np.nanmax(self.values[valid]))
            if math.isclose(xmin, xmax): xmax = xmin + 1.0
            if math.isclose(ymin, ymax):
                pad = max(abs(ymin) * .05, 1.0); ymin, ymax = ymin - pad, ymax + pad
            path, open_segment = QPainterPath(), False
            for time, value in zip(self.times, self.values):
                if not (np.isfinite(time) and np.isfinite(value)):
                    open_segment = False; continue
                px = plot.left() + (float(time) - xmin) / (xmax - xmin) * plot.width()
                py = plot.bottom() - (float(value) - ymin) / (ymax - ymin) * plot.height()
                if open_segment: path.lineTo(QPointF(px, py))
                else: path.moveTo(QPointF(px, py)); open_segment = True
            painter.setPen(QPen(QColor(30, 90, 180), 1.5)); painter.drawPath(path); painter.setPen(QPen(Qt.black, 1))
            painter.drawText(4, plot.top() + 10, f"{ymax:.4g}"); painter.drawText(4, plot.bottom(), f"{ymin:.4g}")
            painter.drawText(plot.right() - 85, plot.bottom() + 20, f"{xmax:.4g} s")
        painter.drawText(plot.center().x() - 75, self.height() - 12, "Simulation time [s]")
        painter.save(); painter.translate(16, plot.center().y() + 65); painter.rotate(-90)
        painter.drawText(0, 0, f"{self.value_label} [{self.unit}]"); painter.restore()


class TimeSeriesPlotDialog(QDialog):
    def __init__(self, times, values, title: str, value_label: str, unit: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.addWidget(TimeSeriesPlotWidget(times, values, value_label, unit, self))


def rheology_zone_summary(model: str, zones) -> str:
    """Describe the solver's altitude-zone lookup in the dialog itself."""
    active = [("μ", 0, ""), ("ξ", 1, " m/s²")]
    if model == "Coulomb":
        active = active[:1]
    elif model == "cohesive_Voellmy":
        active.append(("C", 2, " Pa"))
    values = lambda zone: ", ".join(f"{label} = {zone[index]:g}{unit}" for label, index, unit in active)
    if len(zones) == 1:
        return f"Uniform rheology at all bed elevations: {values(zones[0])}."
    lines: list[str] = []
    for index, zone in enumerate(zones):
        if index == 0:
            extent = f"z < {zones[1][3]:g} m"
        elif index == len(zones) - 1:
            extent = f"z ≥ {zone[3]:g} m"
        else:
            extent = f"{zone[3]:g} m ≤ z < {zones[index + 1][3]:g} m"
        lines.append(f"Zone {index + 1}: {extent}; {values(zone)}")
    return "\n".join(lines)


class RheologyZonePlotWidget(QWidget):
    """Qt-native step plots of AVAC rheology parameters against bed elevation."""

    def __init__(self, model: str, zones, parent=None) -> None:
        super().__init__(parent)
        self.model, self.zones = str(model), list(zones)
        self.setMinimumSize(700, 390)

    def _series(self):
        series = [("μ [-]", 0, QColor("#2d6fb7"))]
        if self.model != "Coulomb":
            series.append(("ξ [m/s²]", 1, QColor("#c97617")))
        if self.model == "cohesive_Voellmy":
            series.append(("C [Pa]", 2, QColor("#5a9a48")))
        return series

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), Qt.white)
        painter.setPen(QPen(Qt.black, 1))
        title = "Altitude-dependent rheology" if len(self.zones) > 1 else "Uniform rheology"
        painter.drawText(0, 4, self.width(), 28, Qt.AlignHCenter, title)
        left, right, top, bottom = 88, 24, 70, 68
        plot_left, plot_right = left, self.width() - right
        plot_top, plot_bottom = top, self.height() - bottom
        series, count = self._series(), len(self._series())
        gap = 22
        panel_width = max(90, (plot_right - plot_left - gap * (count - 1)) / count)
        breaks = [float(zone[3]) for zone in self.zones[1:]]
        if breaks:
            gaps = np.diff(breaks)
            padding = max(25.0, float(np.nanmin(gaps)) * .25 if gaps.size else max(abs(breaks[0]) * .05, 25.0))
            zmin, zmax = breaks[0] - padding, breaks[-1] + padding
        else:
            zmin, zmax = 0.0, 1.0
        if math.isclose(zmin, zmax):
            zmax = zmin + 1.0

        def py(elevation: float) -> float:
            return plot_bottom - (elevation - zmin) / (zmax - zmin) * (plot_bottom - plot_top)

        for number, (label, column, color) in enumerate(series):
            xleft = plot_left + number * (panel_width + gap)
            xright = xleft + panel_width
            values = [float(zone[column]) for zone in self.zones]
            vmin, vmax = min(values), max(values)
            padding = max(abs(vmax - vmin) * .12, abs(vmax) * .08, 0.01)
            if math.isclose(vmin, vmax):
                padding = max(abs(vmax) * .12, 1.0 if column else .02)
            vmin, vmax = vmin - padding, vmax + padding

            def px(value: float) -> float:
                return xleft + (value - vmin) / (vmax - vmin) * panel_width

            painter.setPen(QPen(Qt.black, 1))
            painter.drawLine(round(xleft), round(plot_bottom), round(xright), round(plot_bottom))
            painter.drawLine(round(xleft), round(plot_bottom), round(xleft), round(plot_top))
            painter.drawText(round(xleft), round(plot_top - 18), label)
            painter.drawText(round(xleft), round(plot_bottom + 22), f"{vmin:.4g}")
            painter.drawText(round(xright - 45), round(plot_bottom + 22), f"{vmax:.4g}")
            boundary_pen = QPen(QColor("#9a9a9a"), 1)
            boundary_pen.setStyle(Qt.DashLine)
            painter.setPen(boundary_pen)
            for boundary in breaks:
                painter.drawLine(round(xleft), round(py(boundary)), round(xright), round(py(boundary)))
            step_pen = QPen(color, 2.3)
            painter.setPen(step_pen)
            for index, value in enumerate(values):
                lower = zmin if index == 0 else breaks[index - 1]
                upper = zmax if index == len(values) - 1 else breaks[index]
                painter.drawLine(round(px(value)), round(py(lower)), round(px(value)), round(py(upper)))
                if index:
                    painter.drawLine(round(px(values[index - 1])), round(py(lower)), round(px(value)), round(py(lower)))
            if number == 0:
                painter.setPen(QPen(Qt.black, 1))
                painter.drawText(4, round(plot_top + 10), f"{zmax:g} m")
                painter.drawText(4, round(plot_bottom), f"{zmin:g} m")
                for boundary in breaks:
                    painter.drawText(4, round(py(boundary) + 4), f"{boundary:g}")
        painter.save()
        painter.translate(70, (plot_top + plot_bottom) / 2 + 58)
        painter.rotate(-90)
        painter.drawText(0, 0, "Bed elevation z [m]")
        painter.restore()
        if breaks:
            painter.setPen(QPen(QColor("#555555"), 1))
            painter.drawText(plot_left, self.height() - 12, "Dashed lines are the configured altitude thresholds; lower zones are below the first threshold.")
        else:
            painter.setPen(QPen(QColor("#555555"), 1))
            painter.drawText(plot_left, self.height() - 12, "The selected values apply at all bed elevations.")
        painter.end()


class RheologyZoneDialog(QDialog):
    """Compact visualization and exact textual audit of the active zones."""

    def __init__(self, model: str, zones, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AVAC Rheology by Bed Elevation")
        self.setMinimumSize(740, 510)
        layout = QVBoxLayout(self)
        self.plot = RheologyZonePlotWidget(model, zones, self)
        self.summary_label = QLabel(rheology_zone_summary(model, zones), self)
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.plot)
        layout.addWidget(self.summary_label)


def _draw_wave_cross_section(painter: QPainter, rect, distance, ground, surface, title: str = "") -> None:
    """Render the notebook-style brown ground and blue water cross-section."""
    painter.fillRect(rect, Qt.white)
    plot = rect.adjusted(70, 36, -24, -55)
    painter.setPen(QPen(Qt.black, 1)); painter.drawLine(plot.bottomLeft(), plot.bottomRight()); painter.drawLine(plot.bottomLeft(), plot.topLeft())
    distance, ground, surface = (np.asarray(value, float) for value in (distance, ground, surface))
    valid = np.isfinite(distance) & np.isfinite(ground) & np.isfinite(surface)
    if not np.any(valid):
        painter.drawText(plot, Qt.AlignCenter, "No valid profile samples")
        return
    xmin, xmax = float(np.nanmin(distance[valid])), float(np.nanmax(distance[valid]))
    ymin, ymax = float(np.nanmin(ground[valid]) - 1.0), float(np.nanmax(ground[valid]) + 2.0)
    if math.isclose(xmin, xmax): xmax = xmin + 1.0
    if math.isclose(ymin, ymax): ymax = ymin + 1.0
    def point(index: int, value: float) -> QPointF:
        return QPointF(plot.left() + (distance[index] - xmin) / (xmax - xmin) * plot.width(), plot.bottom() - (value - ymin) / (ymax - ymin) * plot.height())
    terrain = QPainterPath(); ground_line = QPainterPath(); water = QPainterPath(); first = True
    for index in np.flatnonzero(valid):
        p_ground, p_surface = point(index, ground[index]), point(index, surface[index])
        if first:
            terrain.moveTo(p_ground); ground_line.moveTo(p_ground); water.moveTo(p_ground); water.lineTo(p_surface); first = False
        else:
            terrain.lineTo(p_ground); ground_line.lineTo(p_ground); water.lineTo(p_surface)
    # Close fills in the same order used by the notebook's fill_between calls.
    last, first_index = int(np.flatnonzero(valid)[-1]), int(np.flatnonzero(valid)[0])
    terrain.lineTo(point(last, ymin)); terrain.lineTo(point(first_index, ymin)); terrain.closeSubpath()
    water.lineTo(point(last, ground[last]));
    for index in np.flatnonzero(valid)[::-1]: water.lineTo(point(index, ground[index]))
    water.closeSubpath()
    painter.fillPath(terrain, QColor("white")); painter.fillPath(water, QColor("skyblue"))
    painter.setPen(QPen(QColor("sienna"), 1.5)); painter.drawPath(ground_line)
    painter.setPen(QPen(QColor("deepskyblue"), 1.5)); painter.drawPath(water)
    painter.setPen(QPen(Qt.black, 1)); painter.drawText(4, plot.top() + 10, f"{ymax:.4g}"); painter.drawText(4, plot.bottom(), f"{ymin:.4g}")
    painter.drawText(plot.right() - 85, plot.bottom() + 20, f"{xmax:.4g} m")
    painter.drawText(plot.center().x() - 75, rect.bottom() - 12, "Distance along profile [m]")
    if title: painter.drawText(plot.left(), 20, title)


class WaveCrossSectionWidget(QWidget):
    def __init__(self, distance, ground, surface, title: str, parent=None) -> None:
        super().__init__(parent); self.distance, self.ground, self.surface, self.title = distance, ground, surface, title
        self.setMinimumSize(620, 340)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self); _draw_wave_cross_section(painter, self.rect(), self.distance, self.ground, self.surface, self.title); painter.end()


class WaveCrossSectionDialog(QDialog):
    def __init__(self, distance, ground, surface, title: str, parent=None) -> None:
        super().__init__(parent); self.setWindowTitle(title)
        layout = QVBoxLayout(self); layout.addWidget(WaveCrossSectionWidget(distance, ground, surface, title, self))


def write_wave_cross_section_png(path, distance, ground, surface, title: str, width: int = 1200) -> None:
    """Write the same cross-section graphic used by the interactive Wave plot."""
    image = QImage(width, max(360, round(width * .42)), QImage.Format_ARGB32_Premultiplied); image.fill(Qt.white)
    painter = QPainter(image); _draw_wave_cross_section(painter, image.rect(), distance, ground, surface, title); painter.end()
    if not image.save(str(path), "PNG"): raise RuntimeError(f"Could not write Wave profile PNG: {path}")
