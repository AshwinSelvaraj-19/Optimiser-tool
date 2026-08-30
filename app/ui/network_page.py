"""
NETWORK page — ping, jitter, packet loss, gateway, DNS diagnostics.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt, QThread

from app.network.analyzer import network_analyzer
from app.utils.logger import get_logger

logger = get_logger("ui.network_page")


class NetworkRow(QFrame):
    """Compact network metric row."""
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.NoFrame)
        self.setFixedHeight(44)
        self.setStyleSheet("""
            QFrame {
                background-color: #0e0e16;
                border: 1px solid #1a1e28;
                border-radius: 6px;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 6, 14, 6)

        self.label = QLabel(label)
        self.label.setStyleSheet("color: #5a6070; font-size: 11px; font-weight: 600; letter-spacing: 1px; border: none;")
        layout.addWidget(self.label, 1)

        self.value = QLabel("--")
        self.value.setStyleSheet("color: #c8ccd4; font-size: 13px; font-weight: 600; border: none;")
        layout.addWidget(self.value)

    def set_value(self, val: str, color: str = "#c8ccd4"):
        self.value.setText(val)
        self.value.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 600; border: none;")


class NetworkPage(QWidget):
    """Network diagnostics page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("NETWORK")
        title.setStyleSheet("color: #6478ff; font-size: 16px; font-weight: 700; letter-spacing: 2px;")
        layout.addWidget(title)

        note = QLabel("⚠ Network quality affects online latency, not FPS. Improving network does NOT increase frame rate.")
        note.setStyleSheet("color: #ffa940; font-size: 10px; padding: 6px 10px; background-color: #1a1408; border: 1px solid #2a2010; border-radius: 4px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        for key in ["PING", "JITTER", "PACKET LOSS", "GATEWAY", "DNS"]:
            row = NetworkRow(key)
            self._rows[key] = row
            layout.addWidget(row)

        # Analyze button
        btn_layout = QHBoxLayout()
        analyze_btn = QPushButton("ANALYZE NETWORK")
        analyze_btn.setFixedHeight(34)
        analyze_btn.setCursor(Qt.PointingHandCursor)
        analyze_btn.setStyleSheet("""
            QPushButton {
                background-color: #14141c;
                color: #6478ff;
                border: 1px solid #1e2028;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                padding: 0 16px;
            }
            QPushButton:hover { background-color: #1a1e28; }
        """)
        analyze_btn.clicked.connect(self._analyze)
        btn_layout.addWidget(analyze_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()

    def refresh(self):
        pass

    def _analyze(self):
        try:
            report = network_analyzer.analyze()
            if report.ping_results:
                best = min(report.ping_results, key=lambda r: r.avg_latency_ms)
                color = "#40c057" if best.avg_latency_ms < 30 else "#ffa940" if best.avg_latency_ms < 80 else "#ff6b6b"
                self._rows["PING"].set_value(f"{best.avg_latency_ms:.0f} ms", color)

            if report.jitter_reports:
                worst_j = max(report.jitter_reports, key=lambda r: r.jitter_ms)
                color = "#40c057" if worst_j.jitter_ms < 5 else "#ffa940" if worst_j.jitter_ms < 15 else "#ff6b6b"
                self._rows["JITTER"].set_value(f"{worst_j.jitter_ms:.1f} ms", color)

            if report.packet_loss_reports:
                worst_pl = max(report.packet_loss_reports, key=lambda r: r.packet_loss_percent)
                color = "#40c057" if worst_pl.packet_loss_percent < 1 else "#ff6b6b"
                self._rows["PACKET LOSS"].set_value(f"{worst_pl.packet_loss_percent:.1f}%", color)

            self._rows["GATEWAY"].set_value("Analyzed")
            self._rows["DNS"].set_value("Analyzed")
        except Exception as e:
            logger.error(f"Network analysis: {e}")
