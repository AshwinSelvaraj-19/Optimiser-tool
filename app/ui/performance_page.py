"""
PERFORMANCE page — real-time telemetry, bottleneck analysis, FPS stats.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout,
    QProgressBar, QScrollArea
)
from PySide6.QtCore import Qt, QTimer

from app.core.telemetry import telemetry_engine
from app.core.scanner import hardware_scanner
from app.utils.logger import get_logger

logger = get_logger("ui.performance_page")


class TelemetryCard(QFrame):
    """Compact real-time telemetry card."""
    def __init__(self, title: str, unit: str = "%", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.NoFrame)
        self.setMinimumHeight(70)
        self.setMaximumHeight(80)
        self.setStyleSheet("""
            QFrame {
                background-color: #0e0e16;
                border: 1px solid #1a1e28;
                border-radius: 6px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #5a6070; font-size: 9px; font-weight: 600; letter-spacing: 1px; border: none;")

        self.value_label = QLabel("--")
        self.value_label.setStyleSheet("color: #c8ccd4; font-size: 22px; font-weight: 700; border: none;")
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.unit_label = QLabel(unit)
        self.unit_label.setStyleSheet("color: #3a3e48; font-size: 10px; border: none;")

        layout.addWidget(self.title_label)
        h = QHBoxLayout()
        h.setSpacing(4)
        h.addWidget(self.value_label)
        h.addWidget(self.unit_label)
        h.addStretch()
        layout.addLayout(h)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(2)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet("QProgressBar { background-color: #1a1e28; border-radius: 1px; } QProgressBar::chunk { background-color: #6478ff; border-radius: 1px; }")
        layout.addWidget(self.bar)

    def update_value(self, value: float, color: str = "#6478ff"):
        self.value_label.setText(f"{value:.1f}")
        self.value_label.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: 700; border: none;")
        self.bar.setValue(int(min(100, max(0, value))))


class PerformancePage(QWidget):
    """Performance page with real-time telemetry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards = {}
        self._cached_pm_path = None  # Cached PresentMon path (filesystem scan once)
        self._cached_bottleneck = None  # Cached bottleneck from worker
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_telemetry)
        self._timer.start(1000)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("PERFORMANCE")
        title.setStyleSheet("color: #6478ff; font-size: 16px; font-weight: 700; letter-spacing: 2px;")
        layout.addWidget(title)

        # Telemetry grid
        grid = QGridLayout()
        grid.setSpacing(8)

        metrics = [
            ("CPU", "%"), ("GPU", "%"), ("RAM", "%"), ("VRAM", "%"),
            ("GPU TEMP", "°C"), ("CPU TEMP", "°C"), ("GPU CLOCK", "MHz"), ("CPU CLOCK", "MHz"),
        ]
        for i, (name, unit) in enumerate(metrics):
            card = TelemetryCard(name, unit)
            self._cards[name] = card
            grid.addWidget(card, i // 4, i % 4)

        layout.addLayout(grid)

        # FPS Stats section
        fps_section = QHBoxLayout()
        fps_section.setSpacing(8)

        for name, unit in [("FPS", ""), ("1% LOW", "FPS"), ("0.1% LOW", "FPS"), ("FRAME TIME", "ms"), ("FRAME VARIANCE", "ms²")]:
            card = TelemetryCard(name, unit)
            self._cards[name] = card
            fps_section.addWidget(card)

        layout.addLayout(fps_section)

        # Bottleneck panel
        bn_frame = QFrame()
        bn_frame.setStyleSheet("""
            QFrame {
                background-color: #0e0e16;
                border: 1px solid #1a1e28;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        bn_layout = QVBoxLayout(bn_frame)
        bn_layout.setContentsMargins(16, 12, 16, 12)
        bn_layout.setSpacing(4)

        bn_header = QLabel("CURRENT BOTTLENECK")
        bn_header.setStyleSheet("color: #ff6b6b; font-size: 10px; font-weight: 700; letter-spacing: 1px; border: none;")
        bn_layout.addWidget(bn_header)

        self.bottleneck_name = QLabel("SCANNING...")
        self.bottleneck_name.setStyleSheet("color: #c8ccd4; font-size: 14px; font-weight: 600; border: none;")
        bn_layout.addWidget(self.bottleneck_name)

        self.bottleneck_confidence = QLabel("")
        self.bottleneck_confidence.setStyleSheet("color: #5a6070; font-size: 11px; border: none;")
        bn_layout.addWidget(self.bottleneck_confidence)

        self.bottleneck_reason = QLabel("")
        self.bottleneck_reason.setStyleSheet("color: #8090a0; font-size: 11px; border: none;")
        bn_layout.addWidget(self.bottleneck_reason)

        self.bottleneck_actions = QLabel("")
        self.bottleneck_actions.setStyleSheet("color: #40c057; font-size: 11px; border: none;")
        bn_layout.addWidget(self.bottleneck_actions)

        layout.addWidget(bn_frame)
        layout.addStretch()

    def _update_telemetry(self):
        try:
            frame = telemetry_engine.current

            def color_for(val, thresholds=(70, 90)):
                if val < thresholds[0]: return "#40c057"
                elif val < thresholds[1]: return "#ffa940"
                else: return "#ff6b6b"

            self._cards["CPU"].update_value(frame.cpu_utilization, color_for(frame.cpu_utilization))
            self._cards["GPU"].update_value(frame.gpu_utilization, color_for(frame.gpu_utilization))
            self._cards["RAM"].update_value(frame.ram_percent, color_for(frame.ram_percent))

            if frame.gpu_memory_total_mb > 0:
                vram_pct = (frame.gpu_memory_used_mb / frame.gpu_memory_total_mb) * 100
                self._cards["VRAM"].update_value(vram_pct, color_for(vram_pct))
            else:
                self._cards["VRAM"].value_label.setText("N/A")

            if frame.gpu_temp is not None:
                self._cards["GPU TEMP"].update_value(frame.gpu_temp, color_for(frame.gpu_temp, (75, 85)))
            else:
                self._cards["GPU TEMP"].value_label.setText("N/A")

            if frame.cpu_temp is not None:
                self._cards["CPU TEMP"].update_value(frame.cpu_temp, color_for(frame.cpu_temp, (75, 85)))
            else:
                self._cards["CPU TEMP"].value_label.setText("N/A")

            if frame.gpu_clock_mhz > 0:
                self._cards["GPU CLOCK"].update_value(frame.gpu_clock_mhz, "#6478ff")
            else:
                self._cards["GPU CLOCK"].value_label.setText("N/A")

            if frame.cpu_frequency_mhz > 0:
                self._cards["CPU CLOCK"].update_value(frame.cpu_frequency_mhz, "#6478ff")
            else:
                self._cards["CPU CLOCK"].value_label.setText("N/A")

            # FPS — check PresentMon provider status (cached path)
            from app.performance.fps_provider import fps_registry
            if self._cached_pm_path is None:
                from app.performance.presentmon_provider import find_presentmon
                self._cached_pm_path = find_presentmon()
            pm_path = self._cached_pm_path
            fps_status = fps_registry.get_status()

            if pm_path and fps_status.get("available"):
                # PresentMon is available — show provider info
                ver = fps_status.get("version", "")
                self._cards["FPS"].value_label.setText("--")
                self._cards["FPS"].value_label.setStyleSheet("color: #6478ff; font-size: 14px; font-weight: 500; border: none;")
                for key in ["1% LOW", "0.1% LOW", "FRAME TIME", "FRAME VARIANCE"]:
                    self._cards[key].value_label.setText("--")
                    self._cards[key].value_label.setStyleSheet("color: #6478ff; font-size: 14px; font-weight: 500; border: none;")
            else:
                # PresentMon not available
                reason = "PresentMon not found" if not pm_path else fps_status.get("status", "UNAVAILABLE")
                for key in ["FPS", "1% LOW", "0.1% LOW", "FRAME TIME", "FRAME VARIANCE"]:
                    self._cards[key].value_label.setText("N/A")
                    self._cards[key].value_label.setStyleSheet("color: #5a6070; font-size: 11px; font-weight: 500; border: none;")

            # Bottleneck — use cached result (avoid ~11ms on GUI thread every 1s)
            if self._cached_bottleneck is None:
                self._update_bottleneck(frame)
            else:
                self._apply_cached_bottleneck()

        except Exception as e:
            logger.debug(f"Performance update: {e}")

    def _apply_cached_bottleneck(self):
        """Re-apply cached bottleneck result without re-analyzing."""
        analysis = self._cached_bottleneck
        if analysis and analysis.primary_bottleneck:
            bn = analysis.primary_bottleneck
            self.bottleneck_name.setText(bn.name.upper())
            if bn.severity in ("HIGH", "CRITICAL"):
                self.bottleneck_name.setStyleSheet("color: #ff6b6b; font-size: 14px; font-weight: 600; border: none;")
            elif bn.severity == "MEDIUM":
                self.bottleneck_name.setStyleSheet("color: #ffa940; font-size: 14px; font-weight: 600; border: none;")
            else:
                self.bottleneck_name.setStyleSheet("color: #40c057; font-size: 14px; font-weight: 600; border: none;")
            self.bottleneck_confidence.setText(f"Confidence: {bn.confidence * 100:.0f}%")
            self.bottleneck_reason.setText(bn.description)
            self.bottleneck_actions.setText(f"\u2713 {bn.recommendation}")

    def _update_bottleneck(self, frame):
        from app.core.analyzer import bottleneck_analyzer
        analysis = bottleneck_analyzer.analyze(frame)
        self._cached_bottleneck = analysis

        if analysis.primary_bottleneck:
            bn = analysis.primary_bottleneck
            self.bottleneck_name.setText(bn.name.upper())
            if bn.severity in ("HIGH", "CRITICAL"):
                self.bottleneck_name.setStyleSheet("color: #ff6b6b; font-size: 14px; font-weight: 600; border: none;")
            elif bn.severity == "MEDIUM":
                self.bottleneck_name.setStyleSheet("color: #ffa940; font-size: 14px; font-weight: 600; border: none;")
            else:
                self.bottleneck_name.setStyleSheet("color: #40c057; font-size: 14px; font-weight: 600; border: none;")

            self.bottleneck_confidence.setText(f"Confidence: {bn.confidence * 100:.0f}%")
            self.bottleneck_reason.setText(bn.description)
            self.bottleneck_actions.setText(f"✓ {bn.recommendation}")

    def refresh(self):
        self._update_telemetry()
