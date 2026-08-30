"""
Main dashboard page — real-time system overview.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QFrame, QProgressBar, QPushButton, QGroupBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QPalette

from app.core.telemetry import telemetry_engine, TelemetryFrame
from app.core.scanner import hardware_scanner
from app.utils.logger import get_logger

logger = get_logger("ui.dashboard")


class MetricCard(QFrame):
    """A single metric display card."""

    def __init__(self, title: str, unit: str = "%", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setMinimumHeight(100)
        self.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border: 1px solid #16213e;
                border-radius: 8px;
                padding: 10px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #7f8c8d; font-size: 11px; border: none;")
        self.title_label.setAlignment(Qt.AlignCenter)

        self.value_label = QLabel("--")
        self.value_label.setStyleSheet("color: #ecf0f1; font-size: 28px; font-weight: bold; border: none;")
        self.value_label.setAlignment(Qt.AlignCenter)

        self.unit_label = QLabel(unit)
        self.unit_label.setStyleSheet("color: #95a5a6; font-size: 12px; border: none;")
        self.unit_label.setAlignment(Qt.AlignCenter)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setStyleSheet("""
            QProgressBar { background-color: #2c3e50; border-radius: 2px; }
            QProgressBar::chunk { background-color: #3498db; border-radius: 2px; }
        """)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.unit_label)
        layout.addWidget(self.bar)

    def update_value(self, value: float, color: str = "#3498db"):
        self.value_label.setText(f"{value:.1f}")
        self.bar.setValue(int(min(100, max(0, value))))
        self.bar.setStyleSheet(f"""
            QProgressBar {{ background-color: #2c3e50; border-radius: 2px; }}
            QProgressBar::chunk {{ background-color: {color}; border-radius: 2px; }}
        """)

    def set_unavailable(self):
        self.value_label.setText("N/A")
        self.value_label.setStyleSheet("color: #7f8c8d; font-size: 18px; border: none;")


class DashboardPage(QWidget):
    """Dashboard page with real-time metrics overview."""

    optimize_clicked = Signal()
    analyze_clicked = Signal()
    benchmark_clicked = Signal()
    restore_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._start_timer()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = QLabel("PHOENIX FREE FIRE PERFORMANCE OPTIMIZER")
        header.setStyleSheet("color: #e74c3c; font-size: 18px; font-weight: bold; padding: 10px;")
        header.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(header)

        # Status bar
        self.status_label = QLabel("System Ready — Monitoring Active")
        self.status_label.setStyleSheet("color: #2ecc71; font-size: 12px; padding: 5px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.status_label)

        # Metrics grid
        metrics_layout = QGridLayout()
        metrics_layout.setSpacing(12)

        self.cpu_card = MetricCard("CPU", "%")
        self.gpu_card = MetricCard("GPU", "%")
        self.ram_card = MetricCard("RAM", "%")
        self.vram_card = MetricCard("VRAM", "%")
        self.temp_card = MetricCard("TEMP", "°C")
        self.fps_card = MetricCard("FPS", "")
        self.low_card = MetricCard("1% LOW", "FPS")
        self.frame_card = MetricCard("FRAME TIME", "ms")
        self.ping_card = MetricCard("PING", "ms")

        metrics_layout.addWidget(self.cpu_card, 0, 0)
        metrics_layout.addWidget(self.gpu_card, 0, 1)
        metrics_layout.addWidget(self.ram_card, 0, 2)
        metrics_layout.addWidget(self.vram_card, 0, 3)
        metrics_layout.addWidget(self.temp_card, 1, 0)
        metrics_layout.addWidget(self.fps_card, 1, 1)
        metrics_layout.addWidget(self.low_card, 1, 2)
        metrics_layout.addWidget(self.frame_card, 1, 3)
        metrics_layout.addWidget(self.ping_card, 1, 4)

        main_layout.addLayout(metrics_layout)

        # Action buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)

        self.optimize_btn = QPushButton("⚡ MAX FPS OPTIMIZE")
        self.optimize_btn.setMinimumHeight(50)
        self.optimize_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border: none;
                border-radius: 8px;
                padding: 10px 30px;
            }
            QPushButton:hover { background-color: #c0392b; }
            QPushButton:pressed { background-color: #a93226; }
        """)
        self.optimize_btn.clicked.connect(self.optimize_clicked.emit)

        self.analyze_btn = QPushButton("🔍 ANALYZE SYSTEM")
        self.analyze_btn.setMinimumHeight(50)
        self.analyze_btn.setStyleSheet("""
            QPushButton {
                background-color: #2980b9;
                color: white;
                font-size: 14px; font-weight: bold;
                border: none; border-radius: 8px; padding: 10px 20px;
            }
            QPushButton:hover { background-color: #2471a3; }
        """)
        self.analyze_btn.clicked.connect(self.analyze_clicked.emit)

        self.benchmark_btn = QPushButton("🧪 RUN BENCHMARK")
        self.benchmark_btn.setMinimumHeight(50)
        self.benchmark_btn.setStyleSheet("""
            QPushButton {
                background-color: #8e44ad;
                color: white;
                font-size: 14px; font-weight: bold;
                border: none; border-radius: 8px; padding: 10px 20px;
            }
            QPushButton:hover { background-color: #7d3c98; }
        """)
        self.benchmark_btn.clicked.connect(self.benchmark_clicked.emit)

        self.restore_btn = QPushButton("↩ RESTORE")
        self.restore_btn.setMinimumHeight(50)
        self.restore_btn.setStyleSheet("""
            QPushButton {
                background-color: #7f8c8d;
                color: white;
                font-size: 14px; font-weight: bold;
                border: none; border-radius: 8px; padding: 10px 20px;
            }
            QPushButton:hover { background-color: #6c7a7a; }
        """)
        self.restore_btn.clicked.connect(self.restore_clicked.emit)

        buttons_layout.addWidget(self.optimize_btn)
        buttons_layout.addWidget(self.analyze_btn)
        buttons_layout.addWidget(self.benchmark_btn)
        buttons_layout.addWidget(self.restore_btn)

        main_layout.addLayout(buttons_layout)
        main_layout.addStretch()

    def _start_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_metrics)
        self._timer.start(1000)  # Update every second

    def _update_metrics(self):
        try:
            frame = telemetry_engine.current

            # CPU
            self.cpu_card.update_value(
                frame.cpu_utilization,
                "#2ecc71" if frame.cpu_utilization < 70 else "#f39c12" if frame.cpu_utilization < 90 else "#e74c3c"
            )

            # GPU
            self.gpu_card.update_value(
                frame.gpu_utilization,
                "#2ecc71" if frame.gpu_utilization < 70 else "#f39c12" if frame.gpu_utilization < 90 else "#e74c3c"
            )

            # RAM
            self.ram_card.update_value(
                frame.ram_percent,
                "#2ecc71" if frame.ram_percent < 70 else "#f39c12" if frame.ram_percent < 90 else "#e74c3c"
            )

            # VRAM
            if frame.gpu_memory_total_mb > 0:
                vram_pct = (frame.gpu_memory_used_mb / frame.gpu_memory_total_mb) * 100
                self.vram_card.update_value(
                    vram_pct,
                    "#2ecc71" if vram_pct < 70 else "#f39c12" if vram_pct < 90 else "#e74c3c"
                )
            else:
                self.vram_card.set_unavailable()

            # Temperature
            if frame.gpu_temp is not None:
                self.temp_card.update_value(
                    frame.gpu_temp,
                    "#2ecc71" if frame.gpu_temp < 75 else "#f39c12" if frame.gpu_temp < 85 else "#e74c3c"
                )
            elif frame.cpu_temp is not None:
                self.temp_card.update_value(
                    frame.cpu_temp,
                    "#2ecc71" if frame.cpu_temp < 75 else "#f39c12" if frame.cpu_temp < 85 else "#e74c3c"
                )
            else:
                self.temp_card.set_unavailable()

            # FPS / Frame Time — placeholder until benchmark runs
            self.fps_card.set_unavailable()
            self.low_card.set_unavailable()
            self.frame_card.set_unavailable()

            # Ping
            self.ping_card.set_unavailable()

        except Exception as e:
            logger.debug(f"Dashboard update error: {e}")

    def update_with_benchmark(self, fps: float = 0, low_1: float = 0, frame_time: float = 0):
        """Update FPS/frame metrics after benchmark."""
        if fps > 0:
            self.fps_card.update_value(fps, "#2ecc71" if fps >= 55 else "#f39c12" if fps >= 30 else "#e74c3c")
        if low_1 > 0:
            self.low_card.update_value(low_1, "#2ecc71" if low_1 >= 45 else "#f39c12" if low_1 >= 25 else "#e74c3c")
        if frame_time > 0:
            self.frame_card.update_value(frame_time, "#2ecc71" if frame_time <= 17 else "#f39c12" if frame_time <= 33 else "#e74c3c")

    def update_ping(self, latency_ms: float):
        """Update ping display."""
        self.ping_card.update_value(
            latency_ms,
            "#2ecc71" if latency_ms < 30 else "#f39c12" if latency_ms < 80 else "#e74c3c"
        )
