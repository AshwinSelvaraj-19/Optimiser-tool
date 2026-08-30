"""
INPUT page — mouse/display/input diagnostics.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton
)
from PySide6.QtCore import Qt

from app.input.mouse import input_monitor
from app.utils.logger import get_logger

logger = get_logger("ui.input_page")


class InputRow(QFrame):
    """Compact input diagnostic row."""
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


class InputPage(QWidget):
    """Input diagnostics page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("INPUT")
        title.setStyleSheet("color: #6478ff; font-size: 16px; font-weight: 700; letter-spacing: 2px;")
        layout.addWidget(title)

        for key in ["MOUSE POLLING", "DISPLAY REFRESH", "POINTER PRECISION", "VSYNC", "EMULATOR INPUT"]:
            row = InputRow(key)
            self._rows[key] = row
            layout.addWidget(row)

        # Note
        note = QLabel("Input settings diagnostics. End-to-end latency measurement requires external tools.")
        note.setStyleSheet("color: #3a3e48; font-size: 10px; border: none; padding: 8px 0;")
        layout.addWidget(note)

        # Action
        btn_layout = QHBoxLayout()
        disable_btn = QPushButton("DISABLE MOUSE ACCELERATION")
        disable_btn.setFixedHeight(34)
        disable_btn.setCursor(Qt.PointingHandCursor)
        disable_btn.setStyleSheet("""
            QPushButton {
                background-color: #14141c;
                color: #ffa940;
                border: 1px solid #1e2028;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                padding: 0 16px;
            }
            QPushButton:hover { background-color: #1a1e28; }
        """)
        disable_btn.clicked.connect(self._disable_acceleration)
        btn_layout.addWidget(disable_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()

    def refresh(self):
        try:
            config = input_monitor.detect()
            self._rows["DISPLAY REFRESH"].set_value(f"{config.display_refresh_rate}Hz")
            self._rows["VSYNC"].set_value("Unknown")

            precision = "OFF" if not config.mouse.pointer_precision else "ON"
            color = "#40c057" if not config.mouse.pointer_precision else "#ff6b6b"
            self._rows["POINTER PRECISION"].set_value(precision, color)

            self._rows["MOUSE POLLING"].set_value("Unknown")
            self._rows["EMULATOR INPUT"].set_value("Unknown")
        except Exception as e:
            logger.error(f"Input page refresh: {e}")

    def _disable_acceleration(self):
        input_monitor.disable_pointer_precision()
        self.refresh()
