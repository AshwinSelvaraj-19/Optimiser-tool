"""
Heaven Society — Floating Gaming Panel

Compact 450x650 floating control panel designed to be used
beside/over a game. Frameless custom-titlebar with sidebar navigation,
always-on-top toggle, and smooth window dragging.
"""

import json
import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QStackedWidget, QFrame, QSizePolicy, QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QPoint, QSettings
from PySide6.QtGui import QFont, QIcon, QCursor

from app.ui.theme import (
    global_stylesheet, BG_PRIMARY, BG_PANEL, BORDER_LIGHT, BORDER_MEDIUM,
    ACCENT_PRIMARY, ACCENT_LIGHT, ACCENT_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY, TEXT_INVERSE,
    FONT_FAMILY, FONT_MONO,
    FONT_SIZE_SM, FONT_SIZE_XS,
    WEIGHT_BOLD, WEIGHT_SEMIBOLD, WEIGHT_MEDIUM,
    RADIUS_MD, STATUS_OK, STATUS_MUTED, STATUS_WARN,
)
from app.utils.logger import get_logger

logger = get_logger("ui.main_window")

# ── Sizing constants ──────────────────────────────────────────────

PANEL_WIDTH = 900
PANEL_HEIGHT = 650
PANEL_MIN_W = 480
PANEL_MIN_H = 500
PANEL_MAX_W = 1200
PANEL_MAX_H = 1000

HEADER_H = 38
SIDEBAR_W = 50

# ── Navigation items ──────────────────────────────────────────────

NAV_ITEMS = [
    ("⌂",   "home",     "Home"),
    ("⚡",  "optimize", "Optimize"),
    ("📊",  "monitor",  "Monitor"),
    ("🧹",  "cleanup",  "Cleanup"),
    ("🔧",  "tools",    "Tools"),
    ("⚙",   "settings", "Settings"),
]


# ── Sidebar button ────────────────────────────────────────────────

class SidebarButton(QPushButton):
    """Compact icon+tooltip sidebar button."""

    def __init__(self, icon: str, key: str, tooltip: str, parent=None):
        super().__init__(icon, parent)
        self.page_key = key
        self.setCheckable(True)
        self.setFixedSize(SIDEBAR_W - 8, 36)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setToolTip(tooltip)
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
                    font-size: 16px;
                    font-weight: {WEIGHT_BOLD};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {TEXT_TERTIARY};
                    border: none;
                    border-radius: {RADIUS_MD};
                    font-size: 16px;
                }}
                QPushButton:hover {{
                    background-color: {ACCENT_SUBTLE};
                    color: {ACCENT_PRIMARY};
                }}
            """)

    def setActive(self, active: bool):
        self._active = active
        self._apply_style()


# ── Main Window ───────────────────────────────────────────────────

class MainWindow(QMainWindow):
    """Heaven Society — compact floating gaming panel."""

    # Lazy page constructors
    _PAGE_FACTORIES = {
        "home":     ("app.ui.home_page",      "HomePage"),
        "optimize": ("app.ui.optimizer_page",  "OptimizerPage"),
        "monitor":  ("app.ui.monitor_page",    "MonitorPage"),
        "cleanup":  ("app.ui.cleanup_page",    "CleanupPage"),
        "tools":    ("app.ui.tools_page",      "ToolsPage"),
        "settings": ("app.ui.settings_page",   "SettingsPage"),
    }

    def __init__(self):
        super().__init__()
        # Frameless floating panel
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Window
            | Qt.WindowStaysOnTopHint  # default: gaming mode ON
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self.setWindowTitle("Heaven Society")
        self.setMinimumSize(PANEL_MIN_W, PANEL_MIN_H)
        self.setMaximumSize(PANEL_MAX_W, PANEL_MAX_H)
        self.resize(PANEL_WIDTH, PANEL_HEIGHT)

        # State
        self._pages = {}
        self._page_stack_map = {}
        self._nav_buttons = []
        self._gaming_mode = True  # always-on-top by default
        self._drag_pos = None
        self._settings = QSettings("HeavenSociety", "Panel")

        self._setup_ui()
        self.setStyleSheet(global_stylesheet())

        # Restore last position
        self._restore_geometry()

        # Create home page immediately
        self._ensure_page("home")
        self._navigate_to("home")

    # ── UI Setup ──────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(SIDEBAR_W)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border-right: 1px solid {BORDER_LIGHT};
            }}
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(4, 6, 4, 6)
        sidebar_layout.setSpacing(2)

        # Sidebar nav buttons
        for icon, key, tooltip in NAV_ITEMS:
            btn = SidebarButton(icon, key, tooltip)
            btn.clicked.connect(lambda checked, k=key: self._navigate_to(k))
            sidebar_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        sidebar_layout.addStretch()

        # Gaming mode toggle at bottom of sidebar
        self._gm_btn = QPushButton("📌")
        self._gm_btn.setFixedSize(SIDEBAR_W - 8, 32)
        self._gm_btn.setToolTip("Gaming Mode: Always on Top")
        self._gm_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._gm_btn.clicked.connect(self._toggle_gaming_mode)
        self._update_gm_button()
        sidebar_layout.addWidget(self._gm_btn)

        main_layout.addWidget(sidebar)

        # ── Content area ──────────────────────────────────────
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # ── Title bar (draggable) ─────────────────────────────
        title_bar = QFrame()
        title_bar.setFixedHeight(HEADER_H)
        title_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border-bottom: 1px solid {BORDER_LIGHT};
            }}
        """)
        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release
        title_bar.mouseDoubleClickEvent = self._title_double_click
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(10, 0, 6, 0)
        title_bar_layout.setSpacing(8)

        # Logo
        logo = QLabel("HEAVEN SOCIETY")
        logo.setStyleSheet(f"""
            color: {ACCENT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: 10px;
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 2px;
            border: none;
        """)
        title_bar_layout.addWidget(logo)
        title_bar_layout.addStretch()

        # Status indicator
        self._status_label = QLabel("●")
        self._status_label.setStyleSheet(f"""
            color: {STATUS_OK};
            font-size: 8px;
            border: none;
        """)
        self._status_label.setToolTip("System Ready")
        title_bar_layout.addWidget(self._status_label)

        # Window controls
        for icon, slot, tip in [
            ("─", self.showMinimized, "Minimize"),
            ("□", self._toggle_maximize, "Maximize"),
            ("✕", self.close, "Close"),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(24, 24)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {TEXT_TERTIARY};
                    border: none;
                    border-radius: 3px;
                    font-size: 11px;
                    font-weight: {WEIGHT_BOLD};
                }}
                QPushButton:hover {{
                    background-color: {ACCENT_SUBTLE};
                    color: {ACCENT_PRIMARY};
                }}
            """)
            title_bar_layout.addWidget(btn)

        content_layout.addWidget(title_bar)

        # ── Page stack ────────────────────────────────────────
        self._page_stack = QStackedWidget()
        self._page_stack.setStyleSheet(f"""
            QStackedWidget {{
                background-color: {BG_PRIMARY};
                border: none;
            }}
        """)
        content_layout.addWidget(self._page_stack, 1)

        main_layout.addWidget(content, 1)

    # ── Page lazy loading ─────────────────────────────────────

    def _ensure_page(self, key: str):
        if key in self._pages:
            return
        mod_path, cls_name = self._PAGE_FACTORIES[key]
        mod = __import__(mod_path, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        page = cls()
        self._pages[key] = page
        idx = self._page_stack.addWidget(page)
        self._page_stack_map[key] = idx
        if key == "home" and hasattr(page, "navigate_to"):
            page.navigate_to.connect(self._navigate_to)

    def _navigate_to(self, page_key: str):
        for btn in self._nav_buttons:
            btn.setActive(btn.page_key == page_key)
        self._ensure_page(page_key)
        self._page_stack.setCurrentWidget(self._pages[page_key])
        page = self._pages[page_key]
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception as e:
                logger.error(f"Page refresh error ({page_key}): {e}")

    # ── Window dragging ───────────────────────────────────────

    def _title_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _title_mouse_move(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def _title_mouse_release(self, event):
        self._drag_pos = None

    def _title_double_click(self, event):
        self._toggle_maximize()

    # ── Gaming mode (always-on-top) ───────────────────────────

    def _toggle_gaming_mode(self):
        self._gaming_mode = not self._gaming_mode
        self._update_gm_button()
        if self._gaming_mode:
            self.setWindowFlags(
                self.windowFlags() | Qt.WindowStaysOnTopHint
            )
        else:
            self.setWindowFlags(
                self.windowFlags() & ~Qt.WindowStaysOnTopHint
            )
        self.show()

    def _update_gm_button(self):
        if self._gaming_mode:
            self._gm_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ACCENT_PRIMARY};
                    color: #ffffff;
                    border: none;
                    border-radius: {RADIUS_MD};
                    font-size: 14px;
                }}
            """)
            self._gm_btn.setToolTip("Gaming Mode: ON (Always on Top)")
        else:
            self._gm_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {TEXT_TERTIARY};
                    border: none;
                    border-radius: {RADIUS_MD};
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background-color: {ACCENT_SUBTLE};
                    color: {ACCENT_PRIMARY};
                }}
            """)
            self._gm_btn.setToolTip("Gaming Mode: OFF")

    # ── Maximize/restore ──────────────────────────────────────

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ── Status ────────────────────────────────────────────────

    def set_status(self, text: str, color: str = STATUS_OK):
        self._status_label.setStyleSheet(f"""
            color: {color};
            font-size: 8px;
            border: none;
        """)
        self._status_label.setToolTip(text)

    # ── Geometry persistence ──────────────────────────────────

    def _restore_geometry(self):
        try:
            geo = self._settings.value("geometry")
            if geo:
                self.restoreGeometry(geo)
                # Enforce minimum size after restore
                if self.width() < PANEL_MIN_W or self.height() < PANEL_MIN_H:
                    self.resize(
                        max(self.width(), PANEL_MIN_W),
                        max(self.height(), PANEL_MIN_H),
                    )
        except Exception:
            pass

    def _save_geometry(self):
        try:
            self._settings.setValue("geometry", self.saveGeometry())
        except Exception:
            pass

    # ── Close ─────────────────────────────────────────────────

    def closeEvent(self, event):
        self._save_geometry()
        try:
            for page in self._pages.values():
                for attr in dir(page):
                    obj = getattr(page, attr, None)
                    try:
                        from PySide6.QtCore import QTimer
                        if isinstance(obj, QTimer) and obj.isActive():
                            obj.stop()
                    except Exception:
                        pass
                    try:
                        if hasattr(obj, "isRunning") and obj.isRunning():
                            obj.quit()
                            obj.wait(1000)
                    except Exception:
                        pass
            from app.core.telemetry import telemetry_engine
            telemetry_engine.stop()
            from app.system.gpu import gpu_monitor
            gpu_monitor.cleanup()
        except Exception:
            pass
        event.accept()
