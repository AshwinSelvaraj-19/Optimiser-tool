"""
Heaven Society — Main Window

Compact 900×600 desktop utility with horizontal top-tab navigation.
Silver + Red premium gaming aesthetic.
Real-time Free Fire / emulator performance monitoring.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QStackedWidget, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QIcon

from app.ui.theme import (
    global_stylesheet, BG_PRIMARY, BG_PANEL, BORDER_LIGHT, BORDER_MEDIUM,
    ACCENT_PRIMARY, ACCENT_SUBTLE, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    FONT_FAMILY, FONT_SIZE_SM, FONT_SIZE_XS, WEIGHT_BOLD, WEIGHT_SEMIBOLD,
    WEIGHT_MEDIUM, RADIUS_MD, STATUS_OK, STATUS_MUTED,
)
from app.utils.logger import get_logger

logger = get_logger("ui.main_window")

NAV_ITEMS = [
    ("HOME", "home"),
    ("OPTIMIZE", "optimize"),
    ("MONITOR", "monitor"),
    ("CLEANUP", "cleanup"),
    ("TOOLS", "tools"),
    ("SETTINGS", "settings"),
]


class TopTabButton(QPushButton):
    """Horizontal tab button for top navigation bar."""

    def __init__(self, text: str, page_key: str, parent=None):
        super().__init__(text, parent)
        self.page_key = page_key
        self.setCheckable(True)
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)
        self._active = False
        self._apply_style()

    def _apply_style(self):
        if self._active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ACCENT_PRIMARY};
                    color: #ffffff;
                    border: none;
                    border-radius: {RADIUS_MD};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_XS};
                    font-weight: {WEIGHT_BOLD};
                    padding: 0 14px;
                    letter-spacing: 0.8px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {TEXT_TERTIARY};
                    border: none;
                    border-radius: {RADIUS_MD};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_XS};
                    font-weight: {WEIGHT_SEMIBOLD};
                    padding: 0 14px;
                    letter-spacing: 0.5px;
                }}
                QPushButton:hover {{
                    background-color: {ACCENT_SUBTLE};
                    color: {ACCENT_PRIMARY};
                }}
            """)

    def setActive(self, active: bool):
        self._active = active
        self._apply_style()


class MainWindow(QMainWindow):
    """Heaven Society — compact performance utility."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Heaven Society")
        self.setMinimumSize(850, 560)
        self.resize(920, 600)
        self._pages = {}
        self._nav_buttons = []

        self._setup_ui()
        self.setStyleSheet(global_stylesheet())

        self._create_pages()
        self._navigate_to("home")

    def _create_pages(self):
        """Create all pages and add to stack."""
        from app.ui.home_page import HomePage
        from app.ui.optimizer_page import OptimizerPage
        from app.ui.monitor_page import MonitorPage
        from app.ui.cleanup_page import CleanupPage
        from app.ui.tools_page import ToolsPage
        from app.ui.settings_page import SettingsPage

        page_map = {
            "home": HomePage,
            "optimize": OptimizerPage,
            "monitor": MonitorPage,
            "cleanup": CleanupPage,
            "tools": ToolsPage,
            "settings": SettingsPage,
        }

        for key, cls in page_map.items():
            page = cls()
            self._pages[key] = page
            self._page_stack.addWidget(page)

        # Connect home page signals
        home = self._pages["home"]
        if hasattr(home, 'navigate_to'):
            home.navigate_to.connect(self._navigate_to)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Top Bar ──────────────────────────────────────────
        top_bar = QFrame()
        top_bar.setFixedHeight(52)
        top_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border-bottom: 1px solid {BORDER_LIGHT};
            }}
        """)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 0, 16, 0)
        top_layout.setSpacing(0)

        # Logo / App name
        logo = QLabel("HEAVEN SOCIETY")
        logo.setStyleSheet(f"""
            color: {ACCENT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: 14px;
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 3px;
            border: none;
        """)
        top_layout.addWidget(logo)

        top_layout.addSpacing(24)

        # Nav tabs
        for text, key in NAV_ITEMS:
            btn = TopTabButton(text, key)
            btn.clicked.connect(lambda checked, k=key: self._navigate_to(k))
            top_layout.addWidget(btn)
            self._nav_buttons.append(btn)
            top_layout.addSpacing(4)

        top_layout.addStretch()

        # Status indicator
        self._status_label = QLabel("● SYSTEM READY")
        self._status_label.setStyleSheet(f"""
            color: {STATUS_OK};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_SEMIBOLD};
            letter-spacing: 0.5px;
            border: none;
        """)
        top_layout.addWidget(self._status_label)

        main_layout.addWidget(top_bar)

        # ── Page Stack ───────────────────────────────────────
        self._page_stack = QStackedWidget()
        self._page_stack.setStyleSheet(f"QStackedWidget {{ background-color: {BG_PRIMARY}; border: none; }}")
        main_layout.addWidget(self._page_stack)

    def _navigate_to(self, page_key: str):
        if page_key not in self._pages:
            return
        for btn in self._nav_buttons:
            btn.setActive(btn.page_key == page_key)
        self._page_stack.setCurrentWidget(self._pages[page_key])
        page = self._pages[page_key]
        if hasattr(page, 'refresh'):
            try:
                page.refresh()
            except Exception as e:
                logger.error(f"Page refresh error ({page_key}): {e}")

    def set_status(self, text: str, color: str = STATUS_OK):
        self._status_label.setText(f"● {text}")
        self._status_label.setStyleSheet(f"""
            color: {color};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_SEMIBOLD};
            letter-spacing: 0.5px;
            border: none;
        """)

    def closeEvent(self, event):
        try:
            from app.core.telemetry import telemetry_engine
            telemetry_engine.stop()
            from app.system.gpu import gpu_monitor
            gpu_monitor.cleanup()
        except Exception:
            pass
        event.accept()
