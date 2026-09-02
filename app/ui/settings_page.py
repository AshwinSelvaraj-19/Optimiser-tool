"""
Heaven Society — SETTINGS Page

Minimal settings: snapshots, PresentMon path, about.
Only keeps settings that actually affect the application.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt

from app.ui.theme import (
    BG_PANEL, BORDER_LIGHT, BORDER_MEDIUM,
    ACCENT_PRIMARY, ACCENT_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    STATUS_OK, STATUS_WARN, STATUS_ERROR, STATUS_MUTED,
    FONT_FAMILY, FONT_MONO,
    FONT_SIZE_SM, FONT_SIZE_XS, FONT_SIZE_MD,
    WEIGHT_BOLD, WEIGHT_SEMIBOLD, WEIGHT_MEDIUM,
    RADIUS_MD, card_style, button_secondary_style,
    card_title_style, section_header_style,
)
from app.core.snapshot import snapshot_manager
from app.core.rollback import rollback_engine
from app.utils.logger import get_logger

logger = get_logger("ui.settings_page")


class SettingsPage(QWidget):
    """Settings page — minimal, only useful settings."""
    _pm_cache = None      # cached PresentMon path
    _pm_cache_ts = 0.0    # timestamp of cache

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        from PySide6.QtWidgets import QScrollArea as _SA
        from PySide6.QtCore import Qt as _Qt
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = _SA()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(_Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        scroll.setWidget(scroll_content)
        outer.addWidget(scroll)

        title = QLabel("SETTINGS")
        title.setStyleSheet(section_header_style())
        layout.addWidget(title)

        # ── Snapshots ────────────────────────────────────────
        snap_frame = QFrame()
        snap_frame.setStyleSheet(f"""
            QFrame {{
                {card_style()}
            }}
        """)
        snap_layout = QVBoxLayout(snap_frame)
        snap_layout.setContentsMargins(10, 8, 10, 8)
        snap_layout.setSpacing(4)

        snap_header = QHBoxLayout()
        snap_title = QLabel("SNAPSHOTS")
        snap_title.setStyleSheet(card_title_style())
        snap_header.addWidget(snap_title)
        snap_header.addStretch()

        restore_btn = QPushButton("RESTORE LAST")
        restore_btn.setFixedHeight(28)
        restore_btn.setCursor(Qt.PointingHandCursor)
        restore_btn.setStyleSheet(button_secondary_style())
        restore_btn.clicked.connect(self._restore_snapshot)
        snap_header.addWidget(restore_btn)
        snap_layout.addLayout(snap_header)

        self.snapshot_table = QTableWidget(0, 3)
        self.snapshot_table.setHorizontalHeaderLabels(["ID", "TIMESTAMP", "ENTRIES"])
        self.snapshot_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.snapshot_table.setMaximumHeight(120)
        self.snapshot_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_LIGHT};
                border-radius: {RADIUS_MD};
                font-size: {FONT_SIZE_XS};
                font-family: {FONT_MONO};
                gridline-color: {BORDER_LIGHT};
            }}
            QTableWidget::item {{
                padding: 3px 6px;
            }}
            QTableWidget::item:selected {{
                background-color: {ACCENT_SUBTLE};
                color: {ACCENT_PRIMARY};
            }}
            QHeaderView::section {{
                background-color: {BORDER_LIGHT};
                color: {TEXT_SECONDARY};
                border: none;
                border-bottom: 1px solid {BORDER_MEDIUM};
                padding: 4px 6px;
                font-size: {FONT_SIZE_XS};
                font-weight: {WEIGHT_SEMIBOLD};
            }}
        """)
        snap_layout.addWidget(self.snapshot_table)

        layout.addWidget(snap_frame)

        # ── PresentMon Info ──────────────────────────────────
        pm_frame = QFrame()
        pm_frame.setStyleSheet(f"""
            QFrame {{
                {card_style()}
            }}
        """)
        pm_layout = QVBoxLayout(pm_frame)
        pm_layout.setContentsMargins(10, 8, 10, 8)
        pm_layout.setSpacing(3)

        pm_title = QLabel("PRESENTMON")
        pm_title.setStyleSheet(card_title_style())
        pm_layout.addWidget(pm_title)

        self.pm_info = QLabel("Checking...")
        self.pm_info.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        pm_layout.addWidget(self.pm_info)

        layout.addWidget(pm_frame)

        # ── About ────────────────────────────────────────────
        about_frame = QFrame()
        about_frame.setStyleSheet(f"""
            QFrame {{
                {card_style()}
            }}
        """)
        about_layout = QVBoxLayout(about_frame)
        about_layout.setContentsMargins(10, 8, 10, 8)
        about_layout.setSpacing(3)

        about_title = QLabel("HEAVEN SOCIETY")
        about_title.setStyleSheet(section_header_style())
        about_layout.addWidget(about_title)

        about_text = QLabel(
            "Free Fire / Emulator Performance Utility\n"
            "Real-time monitoring, optimization, and benchmarking.\n"
            "v1.0.0"
        )
        about_text.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)

        layout.addWidget(about_frame)
        layout.addStretch()

    def refresh(self):
        self._load_snapshots()
        self._load_pm_info()

    def _load_snapshots(self):
        try:
            snapshots = snapshot_manager.list_snapshots()
            self.snapshot_table.setRowCount(len(snapshots))
            for i, s in enumerate(snapshots):
                self.snapshot_table.setItem(i, 0, QTableWidgetItem(s["snapshot_id"]))
                self.snapshot_table.setItem(i, 1, QTableWidgetItem(s["timestamp"][:19]))
                self.snapshot_table.setItem(i, 2, QTableWidgetItem(str(s["entry_count"])))
        except Exception as e:
            logger.debug(f"Snapshot load: {e}")

    def _load_pm_info(self):
        import time as _time
        # Cache PresentMon path for 60 seconds to avoid repeated filesystem scans
        now = _time.time()
        if SettingsPage._pm_cache is not None and (now - SettingsPage._pm_cache_ts) < 60:
            pm_path = SettingsPage._pm_cache
        else:
            try:
                from app.performance.presentmon_provider import find_presentmon
                pm_path = find_presentmon()
            except Exception:
                pm_path = None
            SettingsPage._pm_cache = pm_path
            SettingsPage._pm_cache_ts = now
        try:
            if pm_path:
                from app.performance.presentmon_provider import get_presentmon_version
                ver = get_presentmon_version(pm_path)
                self.pm_info.setText(
                    f"Status: {STATUS_OK.replace('<span style=\"color:', '').replace('\">', '')} READY\n"
                    f"Version: {ver or 'Unknown'}\n"
                    f"Path: {pm_path}"
                )
                self.pm_info.setStyleSheet(f"""
                    color: {STATUS_OK};
                    font-family: {FONT_MONO};
                    font-size: {FONT_SIZE_XS};
                    border: none;
                """)
            else:
                self.pm_info.setText("Status: NOT FOUND\nInstall from GitHub releases")
                self.pm_info.setStyleSheet(f"""
                    color: {STATUS_ERROR};
                    font-family: {FONT_MONO};
                    font-size: {FONT_SIZE_XS};
                    border: none;
                """)
        except Exception as e:
            self.pm_info.setText(f"Error: {e}")
            self.pm_info.setStyleSheet(f"""
                color: {STATUS_ERROR};
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_XS};
                border: none;
            """)

    def _restore_snapshot(self):
        result = rollback_engine.rollback_latest()
        logger.info(f"Restore: {result.message}")
        self.refresh()
