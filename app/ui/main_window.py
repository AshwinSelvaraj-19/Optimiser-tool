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

    # Lazy page constructors — imported only on first visit
    _PAGE_FACTORIES = {
        "home": ("app.ui.home_page", "HomePage"),
        "optimize": ("app.ui.optimizer_page", "OptimizerPage"),
        "monitor": ("app.ui.monitor_page", "MonitorPage"),
        "cleanup": ("app.ui.cleanup_page", "CleanupPage"),
        "tools": ("app.ui.tools_page", "ToolsPage"),
        "settings": ("app.ui.settings_page", "SettingsPage"),
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Heaven Society")
        self.setMinimumSize(850, 560)
        self.resize(920, 600)
        self._pages = {}         # key -> page instance (lazily created)
        self._page_stack_map = {} # key -> index in QStackedWidget
        self._nav_buttons = []
        self._loading_label = None  # placeholder shown while page loads

        self._setup_ui()
        self.setStyleSheet(global_stylesheet())

        # Create only the home page immediately (fast)
        self._ensure_page("home")
        self._navigate_to("home")

    def _ensure_page(self, key: str):
        """Lazily construct a page on first visit."""
        if key in self._pages:
            return
        mod_path, cls_name = self._PAGE_FACTORIES[key]
        mod = __import__(mod_path, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        page = cls()
        self._pages[key] = page
        idx = self._page_stack.addWidget(page)
        self._page_stack_map[key] = idx
        # Connect home page signals
        if key == "home" and hasattr(page, "navigate_to"):
            page.navigate_to.connect(self._navigate_to)

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
        for btn in self._nav_buttons:
            btn.setActive(btn.page_key == page_key)
        # Lazily construct page on first visit
        self._ensure_page(page_key)
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
            # Stop all page timers and workers
            for page in self._pages.values():
                for attr in dir(page):
                    obj = getattr(page, attr, None)
                    try:
                        from PySide6.QtCore import QTimer
                        if isinstance(obj, QTimer) and obj.isActive():
                            obj.stop()
                    except Exception:
                        pass
                    # Stop worker threads
                    try:
                        if hasattr(obj, "isRunning") and obj.isRunning():
                            obj.quit()
                            obj.wait(1000)
                    except Exception:
                        pass
            # Stop telemetry
            from app.core.telemetry import telemetry_engine
            telemetry_engine.stop()
            from app.system.gpu import gpu_monitor
            gpu_monitor.cleanup()
        except Exception:
            pass
        event.accept()
