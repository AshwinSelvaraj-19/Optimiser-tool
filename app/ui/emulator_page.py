"""
EMULATOR page — detection, configuration, backup/modify/restore.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea
)
from PySide6.QtCore import Qt

from app.emulator.detector import emulator_detector
from app.utils.logger import get_logger

logger = get_logger("ui.emulator_page")


class ConfigRow(QFrame):
    """Compact configuration row."""
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.NoFrame)
        self.setFixedHeight(32)
        self.setStyleSheet("QFrame { background-color: transparent; border: none; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self.label = QLabel(label)
        self.label.setFixedWidth(130)
        self.label.setStyleSheet("color: #5a6070; font-size: 11px; border: none;")
        layout.addWidget(self.label)

        self.value = QLabel("--")
        self.value.setStyleSheet("color: #c8ccd4; font-size: 12px; border: none;")
        layout.addWidget(self.value, 1)

        self.status = QLabel("")
        self.status.setFixedWidth(80)
        self.status.setStyleSheet("color: #5a6070; font-size: 10px; border: none;")
        layout.addWidget(self.status)


class EmulatorPage(QWidget):
    """Emulator page with detection and configuration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config_rows = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("EMULATOR")
        title.setStyleSheet("color: #6478ff; font-size: 16px; font-weight: 700; letter-spacing: 2px;")
        header_row.addWidget(title)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Emulator info card
        self.info_card = QFrame()
        self.info_card.setStyleSheet("""
            QFrame {
                background-color: #0e0e16;
                border: 1px solid #1a1e28;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        info_layout = QVBoxLayout(self.info_card)
        info_layout.setContentsMargins(16, 12, 16, 12)
        info_layout.setSpacing(4)

        self.emu_name = QLabel("MSI APP PLAYER")
        self.emu_name.setStyleSheet("color: #e0e4ec; font-size: 16px; font-weight: 700; border: none;")
        info_layout.addWidget(self.emu_name)

        self.emu_status = QLabel("Detecting...")
        self.emu_status.setStyleSheet("color: #5a6070; font-size: 11px; border: none;")
        info_layout.addWidget(self.emu_status)

        layout.addWidget(self.info_card)

        # Configuration section
        config_header = QHBoxLayout()
        config_title = QLabel("CONFIGURATION")
        config_title.setStyleSheet("color: #3a3e48; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        config_header.addWidget(config_title)
        config_header.addStretch()
        layout.addLayout(config_header)

        # Config rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        config_widget = QWidget()
        config_widget.setStyleSheet("background-color: transparent;")
        config_layout = QVBoxLayout(config_widget)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(2)

        for key in ["CPU CORES", "RAM", "RESOLUTION", "DPI", "FPS LIMIT", "RENDERER", "GPU", "VSYNC"]:
            row = ConfigRow(key)
            self._config_rows[key] = row
            config_layout.addWidget(row)

        config_layout.addStretch()
        scroll.setWidget(config_widget)
        layout.addWidget(scroll, 1)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        for text, color in [("BACKUP", "#ffa940"), ("MODIFY", "#6478ff"), ("RESTORE", "#ff6b6b")]:
            btn = QPushButton(text)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #14141c;
                    color: {color};
                    border: 1px solid #1e2028;
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: 600;
                    padding: 0 16px;
                    letter-spacing: 1px;
                }}
                QPushButton:hover {{ background-color: #1a1e28; }}
            """)
            btn_layout.addWidget(btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def refresh(self):
        try:
            emulators = emulator_detector.detect_all()
            if emulators:
                primary = emulators[0]
                running = primary.info.is_running
                self.emu_name.setText(primary.DISPLAY_NAME)

                if running:
                    self.emu_status.setText("● RUNNING")
                    self.emu_status.setStyleSheet("color: #40c057; font-size: 11px; border: none;")
                else:
                    self.emu_status.setText("● NOT RUNNING")
                    self.emu_status.setStyleSheet("color: #ff6b6b; font-size: 11px; border: none;")

                self._config_rows["CPU CORES"].value.setText("Auto")
                self._config_rows["RAM"].value.setText("Auto")
                self._config_rows["RESOLUTION"].value.setText("Auto")
                self._config_rows["FPS LIMIT"].value.setText("60")
                self._config_rows["RENDERER"].value.setText("Auto")
                self._config_rows["GPU"].value.setText("Auto")
                self._config_rows["VSYNC"].value.setText("Unknown")
            else:
                self.emu_name.setText("NO EMULATOR DETECTED")
                self.emu_status.setText("Install MSI App Player")
                self.emu_status.setStyleSheet("color: #5a6070; font-size: 11px; border: none;")
        except Exception as e:
            logger.error(f"Emulator page refresh: {e}")
