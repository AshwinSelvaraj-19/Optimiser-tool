"""
Heaven Society — Floating Gaming Panel + Normal Window

Dual-mode application:
- Panel Mode: compact frameless floating panel (420–520px)
- Normal Mode: conventional desktop window (900×650)

Features:
- Always-on-top toggle (persisted)
- Mode persistence via QSettings
- Off-screen geometry recovery
- Compact tab navigation in panel mode
- Sidebar navigation in normal mode
- Draggable custom title bar in panel mode
"""

import json
import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QStackedWidget, QFrame, QSizePolicy, QScrollArea,
    QTabBar, QSpacerItem,
)
from PySide6.QtCore import Qt, Signal, QPoint, QSettings, QRect, QTimer
from PySide6.QtGui import QFont, QIcon, QCursor, QGuiApplication

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

# ── Panel mode constants ──────────────────────────────────────────

PANEL_W = 480
PANEL_H = 640
PANEL_MIN_W = 400
PANEL_MIN_H = 500
PANEL_MAX_W = 520
PANEL_MAX_H = 800

# ── Normal mode constants ─────────────────────────────────────────

NORMAL_W = 900
NORMAL_H = 650
NORMAL_MIN_W = 700
NORMAL_MIN_H = 500
NORMAL_MAX_W = 1920
NORMAL_MAX_H = 1080

# ── Common constants ──────────────────────────────────────────────

HEADER_H = 32
SIDEBAR_W = 50
TAB_BAR_H = 32

# ── Navigation items ──────────────────────────────────────────────

NAV_ITEMS = [
    ("⌂",   "home",     "Home"),
    ("⚡",  "optimize", "Optimize"),
    ("📊",  "monitor",  "Monitor"),
    ("🧹",  "cleanup",  "Cleanup"),
    ("🔧",  "tools",    "Tools"),
    ("⚙",   "settings", "Settings"),
]


# ── Sidebar button (normal mode) ─────────────────────────────────

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


# ── Tab button (panel mode) ──────────────────────────────────────

class TabButton(QPushButton):
    """Compact tab-style button for panel navigation."""

    def __init__(self, icon: str, key: str, tooltip: str, parent=None):
        super().__init__(f"{icon}", parent)
        self.page_key = key
        self.setCheckable(True)
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
                    border-radius: 4px;
                    font-size: 13px;
                    font-weight: {WEIGHT_BOLD};
                    padding: 3px 5px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {TEXT_TERTIARY};
                    border: none;
                    border-radius: 4px;
                    font-size: 13px;
                    padding: 3px 5px;
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
    """Heaven Society — dual-mode floating gaming panel / normal window."""

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
        self._settings = QSettings("HeavenSociety", "Panel")

        # Persisted preferences
        self._always_on_top = self._settings.value("always_on_top", False, type=bool)
        self._panel_mode = self._settings.value("panel_mode", True, type=bool)
        self._gaming_mode = self._settings.value("gaming_mode", False, type=bool)
        self._shader_enabled = self._settings.value("shader_enabled", True, type=bool)
        self._shader_quality = self._settings.value("shader_quality", "LOW", type=str)

        # Shader widget (initialized in _setup_ui)
        self._shader_widget = None

        # Mutable state
        self._pages = {}
        self._page_stack_map = {}
        self._nav_buttons = []
        self._tab_buttons = []
        self._drag_pos = None
        self._current_page_key = "home"

        # UI elements that change between modes
        self._sidebar_widget = None
        self._tab_bar_widget = None
        self._title_bar_widget = None
        self._page_stack = None

        # Apply window flags first (before setup)
        self._apply_flags()

        self.setWindowTitle("Heaven Society")
        self._apply_size_constraints()

        self._setup_ui()
        self.setStyleSheet(global_stylesheet())

        # Restore geometry with off-screen recovery
        self._restore_geometry()

        # If no saved geometry, use mode-appropriate default size
        key = "panel_geometry" if self._panel_mode else "normal_geometry"
        if not self._settings.contains(key):
            if self._panel_mode:
                self.resize(PANEL_W, PANEL_H)
            else:
                self.resize(NORMAL_W, NORMAL_H)

        # Create home page
        self._ensure_page("home")
        self._navigate_to("home")

        # Preload heavy page imports in a background thread so first
        # navigation is instant.  The thread only imports modules — it
        # never touches Qt widgets.
        import threading as _threading
        def _bg_preload():
            import importlib
            for mod_path in (
                "app.ui.optimizer_page",
                "app.ui.monitor_page",
                "app.ui.cleanup_page",
                "app.ui.tools_page",
                "app.ui.settings_page",
            ):
                try:
                    importlib.import_module(mod_path)
                except Exception:
                    pass
        _threading.Thread(target=_bg_preload, daemon=True, name="page_preload").start()

        # Check for incomplete gaming sessions from a previous crash/exit
        # Run on a background thread to avoid blocking the GUI (~2s I/O)
        _threading.Thread(
            target=self._check_incomplete_sessions,
            daemon=True,
            name="session_recovery",
        ).start()

    # ── Shader Background ──────────────────────────────────────

    def _init_shader(self):
        """Initialize the real-time shader background widget."""
        try:
            from app.ui.shader_widget import ShaderWidget
            self._shader_widget = ShaderWidget(
                self.centralWidget(),
                enabled=self._shader_enabled,
                quality=self._shader_quality,
            )
            self._shader_widget.lower()  # Send behind all other widgets
            # Trigger initial resize
            if self.centralWidget():
                self._shader_widget.setGeometry(self.centralWidget().rect())
        except Exception as e:
            logger.debug(f"Shader init failed (non-critical): {e}")
            self._shader_widget = None

    def set_shader_enabled(self, enabled: bool):
        """Toggle the shader background."""
        self._shader_enabled = enabled
        self._settings.setValue("shader_enabled", enabled)
        if self._shader_widget:
            self._shader_widget.set_enabled(enabled)

    def set_shader_quality(self, quality: str):
        """Change shader quality level."""
        self._shader_quality = quality
        self._settings.setValue("shader_quality", quality)
        if self._shader_widget:
            self._shader_widget.set_quality(quality)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._shader_widget and self._shader_widget.isVisible():
            self._shader_widget.setGeometry(self.centralWidget().rect())

    def _check_incomplete_sessions(self):
        """Recover gaming sessions interrupted by abnormal shutdown.
        
        Delegates to GamingLifecycleManager.recover_incomplete_sessions()
        which handles:
        - Early states: mark FAILED, no restoration needed
        - Applied changes: restore each reversible change individually
        - Partial failures: continue restoring remaining changes
        - Idempotent: skip already-recovered sessions
        - Corrupted files: skip with warning
        - Missing rollback data: mark IRREVERSIBLE
        """
        try:
            from app.gaming.gaming_lifecycle import gaming_lifecycle

            results = gaming_lifecycle.recover_incomplete_sessions()

            for r in results:
                status = r.get("recovery_status", "?")
                sid = r.get("session_id", "?")
                restored = r.get("changes_restored", 0)
                failed = r.get("changes_failed", 0)

                if status == "RECOVERED":
                    logger.info(
                        f"Session recovery OK: {sid} — "
                        f"restored {restored} change(s)"
                    )
                elif status == "PARTIAL_RECOVERY":
                    logger.warning(
                        f"Partial recovery: {sid} — "
                        f"restored {restored}, failed {failed}"
                    )
                elif status == "RECOVERY_FAILED":
                    logger.error(
                        f"Recovery failed: {sid} — "
                        f"all {failed} restore(s) failed"
                    )
                elif status == "NO_RESTORE_NEEDED":
                    logger.info(
                        f"Session cleanup: {sid} — no restore needed"
                    )
        except Exception as e:
            logger.debug(f"Session recovery check: {e}")

    # ── Window flags ──────────────────────────────────────────

    def _apply_flags(self):
        flags = Qt.Window
        if self._panel_mode:
            flags |= Qt.FramelessWindowHint
        if self._always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _apply_size_constraints(self):
        if self._panel_mode:
            self.setMinimumSize(PANEL_MIN_W, PANEL_MIN_H)
            self.setMaximumSize(PANEL_MAX_W, PANEL_MAX_H)
            if self.width() > PANEL_MAX_W or self.height() > PANEL_MAX_H:
                self.resize(
                    min(self.width(), PANEL_MAX_W),
                    min(self.height(), PANEL_MAX_H),
                )
            elif self.width() < PANEL_MIN_W:
                self.resize(PANEL_W, PANEL_H)
        else:
            self.setMinimumSize(NORMAL_MIN_W, NORMAL_MIN_H)
            self.setMaximumSize(NORMAL_MAX_W, NORMAL_MAX_H)

    # ── UI Setup ──────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        self._main_layout = QHBoxLayout(central)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        if self._panel_mode:
            self._setup_panel_ui()
        else:
            self._setup_normal_ui()

        # Initialize shader background
        self._init_shader()

    def _setup_panel_ui(self):
        """Panel mode: title bar + tab bar + page stack (no sidebar)."""
        # Replace horizontal layout with vertical
        old_layout = self.centralWidget().layout()
        if old_layout:
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
        # Remove old layout
        QWidget().setLayout(old_layout) if old_layout else None

        v_layout = QVBoxLayout(self.centralWidget())
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(0)

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
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(10, 0, 6, 0)
        tb_layout.setSpacing(6)

        logo = QLabel("HS")
        logo.setStyleSheet(f"""
            color: {ACCENT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: 12px;
            font-weight: {WEIGHT_BOLD};
            border: none;
        """)
        tb_layout.addWidget(logo)

        title = QLabel("HEAVEN SOCIETY")
        title.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_FAMILY};
            font-size: 9px;
            font-weight: {WEIGHT_SEMIBOLD};
            letter-spacing: 1px;
            border: none;
        """)
        tb_layout.addWidget(title)
        tb_layout.addStretch()

        self._status_label = QLabel("●")
        self._status_label.setStyleSheet(f"color: {STATUS_OK}; font-size: 8px; border: none;")
        self._status_label.setToolTip("System Ready")
        tb_layout.addWidget(self._status_label)

        # Mode switcher
        mode_btn = QPushButton("⬜")
        mode_btn.setFixedSize(22, 22)
        mode_btn.setCursor(QCursor(Qt.PointingHandCursor))
        mode_btn.setToolTip("Switch to Normal Mode")
        mode_btn.clicked.connect(self._toggle_mode)
        mode_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {TEXT_TERTIARY};
                border: none; border-radius: 3px; font-size: 10px; font-weight: bold; }}
            QPushButton:hover {{ background: {ACCENT_SUBTLE}; color: {ACCENT_PRIMARY}; }}
        """)
        tb_layout.addWidget(mode_btn)

        # Always-on-top pin
        self._pin_btn = QPushButton("📌")
        self._pin_btn.setFixedSize(22, 22)
        self._pin_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._pin_btn.clicked.connect(self._toggle_always_on_top)
        self._update_pin_button()
        tb_layout.addWidget(self._pin_btn)

        # Minimize
        min_btn = QPushButton("─")
        min_btn.setFixedSize(22, 22)
        min_btn.setCursor(QCursor(Qt.PointingHandCursor))
        min_btn.clicked.connect(self.showMinimized)
        min_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {TEXT_TERTIARY};
                border: none; border-radius: 3px; font-size: 10px; font-weight: bold; }}
            QPushButton:hover {{ background: {ACCENT_SUBTLE}; color: {ACCENT_PRIMARY}; }}
        """)
        tb_layout.addWidget(min_btn)

        # Close
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {TEXT_TERTIARY};
                border: none; border-radius: 3px; font-size: 10px; font-weight: bold; }}
            QPushButton:hover {{ background: #c41e3a; color: #ffffff; }}
        """)
        tb_layout.addWidget(close_btn)

        v_layout.addWidget(title_bar)
        self._title_bar_widget = title_bar

        # ── Tab bar ───────────────────────────────────────────
        tab_frame = QFrame()
        tab_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border-bottom: 1px solid {BORDER_LIGHT};
            }}
        """)
        tab_layout = QHBoxLayout(tab_frame)
        tab_layout.setContentsMargins(4, 3, 4, 3)
        tab_layout.setSpacing(1)

        for icon, key, tooltip in NAV_ITEMS:
            btn = TabButton(icon, key, tooltip)
            btn.clicked.connect(lambda checked, k=key: self._navigate_to(k))
            tab_layout.addWidget(btn)
            self._tab_buttons.append(btn)

        tab_layout.addStretch()

        v_layout.addWidget(tab_frame)
        self._tab_bar_widget = tab_frame

        # ── Page stack ────────────────────────────────────────
        self._page_stack = QStackedWidget()
        self._page_stack.setStyleSheet(f"""
            QStackedWidget {{
                background-color: {BG_PRIMARY};
                border: none;
            }}
        """)
        v_layout.addWidget(self._page_stack, 1)

    def _setup_normal_ui(self):
        """Normal mode: sidebar + title bar + page stack."""
        # Clear existing layout
        old_layout = self.centralWidget().layout()
        if old_layout:
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)

        layout = QHBoxLayout(self.centralWidget())
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(SIDEBAR_W)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border-right: 1px solid {BORDER_LIGHT};
            }}
        """)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(4, 6, 4, 6)
        sb_layout.setSpacing(2)

        for icon, key, tooltip in NAV_ITEMS:
            btn = SidebarButton(icon, key, tooltip)
            btn.clicked.connect(lambda checked, k=key: self._navigate_to(k))
            sb_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        sb_layout.addStretch()

        # Always-on-top
        self._pin_btn = QPushButton("📌")
        self._pin_btn.setFixedSize(SIDEBAR_W - 8, 32)
        self._pin_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._pin_btn.clicked.connect(self._toggle_always_on_top)
        self._update_pin_button()
        sb_layout.addWidget(self._pin_btn)

        # Mode switcher (normal → panel)
        mode_btn = QPushButton("📱")
        mode_btn.setFixedSize(SIDEBAR_W - 8, 32)
        mode_btn.setCursor(QCursor(Qt.PointingHandCursor))
        mode_btn.setToolTip("Switch to Panel Mode")
        mode_btn.clicked.connect(self._toggle_mode)
        mode_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {TEXT_TERTIARY};
                border: none; border-radius: {RADIUS_MD}; font-size: 14px; }}
            QPushButton:hover {{ background: {ACCENT_SUBTLE}; color: {ACCENT_PRIMARY}; }}
        """)
        sb_layout.addWidget(mode_btn)

        layout.addWidget(sidebar)
        self._sidebar_widget = sidebar

        # ── Content area ──────────────────────────────────────
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Title bar (not frameless in normal mode, but keep compact header)
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
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(10, 0, 6, 0)
        tb_layout.setSpacing(8)

        logo = QLabel("HEAVEN SOCIETY")
        logo.setStyleSheet(f"""
            color: {ACCENT_PRIMARY}; font-family: {FONT_FAMILY};
            font-size: 10px; font-weight: {WEIGHT_BOLD};
            letter-spacing: 2px; border: none;
        """)
        tb_layout.addWidget(logo)
        tb_layout.addStretch()

        self._status_label = QLabel("●")
        self._status_label.setStyleSheet(f"color: {STATUS_OK}; font-size: 8px; border: none;")
        self._status_label.setToolTip("System Ready")
        tb_layout.addWidget(self._status_label)

        content_layout.addWidget(title_bar)

        self._page_stack = QStackedWidget()
        self._page_stack.setStyleSheet(f"""
            QStackedWidget {{ background-color: {BG_PRIMARY}; border: none; }}
        """)
        content_layout.addWidget(self._page_stack, 1)

        layout.addWidget(content, 1)

        self._title_bar_widget = title_bar

    # ── Mode switching ────────────────────────────────────────

    def _toggle_mode(self):
        """Switch between panel and normal mode."""
        self._panel_mode = not self._panel_mode
        self._settings.setValue("panel_mode", self._panel_mode)

        # Save current page
        current_page = self._current_page_key

        # Apply flags
        self._apply_flags()

        # Resize constraints
        self._apply_size_constraints()

        # Set default size if no saved geometry exists
        key = "panel_geometry" if self._panel_mode else "normal_geometry"
        if not self._settings.contains(key):
            if self._panel_mode:
                self.resize(PANEL_W, PANEL_H)
            else:
                self.resize(NORMAL_W, NORMAL_H)

        # Rebuild UI
        self._nav_buttons = []
        self._tab_buttons = []
        self._sidebar_widget = None
        self._tab_bar_widget = None
        self._title_bar_widget = None

        self._setup_ui()
        self.setStyleSheet(global_stylesheet())

        # Restore page
        self._ensure_page(current_page)
        self._navigate_to(current_page)

        # Restore geometry for the new mode
        self._restore_geometry()

        self.show()

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
        self._current_page_key = page_key

        # Update panel tab buttons
        for btn in self._tab_buttons:
            btn.setActive(btn.page_key == page_key)

        # Update normal sidebar buttons
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

    # ── Window dragging (panel mode) ──────────────────────────

    def _title_mouse_press(self, event):
        if event.button() == Qt.LeftButton and self._panel_mode:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _title_mouse_move(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def _title_mouse_release(self, event):
        self._drag_pos = None

    # ── Always-on-top ─────────────────────────────────────────

    def _toggle_always_on_top(self):
        self._always_on_top = not self._always_on_top
        self._settings.setValue("always_on_top", self._always_on_top)
        self._update_pin_button()
        self._apply_flags()
        self.show()

    def _update_pin_button(self):
        if self._always_on_top:
            self._pin_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ACCENT_PRIMARY}; color: #ffffff;
                    border: none; border-radius: {RADIUS_MD}; font-size: 14px;
                }}
            """)
            self._pin_btn.setToolTip("Always on Top: ON")
        else:
            self._pin_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent; color: {TEXT_TERTIARY};
                    border: none; border-radius: {RADIUS_MD}; font-size: 14px;
                }}
                QPushButton:hover {{
                    background-color: {ACCENT_SUBTLE}; color: {ACCENT_PRIMARY};
                }}
            """)
            self._pin_btn.setToolTip("Always on Top: OFF")

    # ── Status ────────────────────────────────────────────────

    def set_status(self, text: str, color: str = STATUS_OK):
        self._status_label.setStyleSheet(f"color: {color}; font-size: 8px; border: none;")
        self._status_label.setToolTip(text)

    # ── Geometry persistence + off-screen recovery ────────────

    def _restore_geometry(self):
        try:
            key = "panel_geometry" if self._panel_mode else "normal_geometry"
            geo = self._settings.value(key)
            if geo:
                self.restoreGeometry(geo)
                # Enforce min size
                min_w = PANEL_MIN_W if self._panel_mode else NORMAL_MIN_W
                min_h = PANEL_MIN_H if self._panel_mode else NORMAL_MIN_H
                if self.width() < min_w or self.height() < min_h:
                    self.resize(max(self.width(), min_w), max(self.height(), min_h))
                # Enforce max size
                max_w = PANEL_MAX_W if self._panel_mode else NORMAL_MAX_W
                max_h = PANEL_MAX_H if self._panel_mode else NORMAL_MAX_H
                if self.width() > max_w or self.height() > max_h:
                    self.resize(min(self.width(), max_w), min(self.height(), max_h))
                self._ensure_visible_on_screen()
        except Exception:
            pass

    def _ensure_visible_on_screen(self):
        frame = self.frameGeometry()
        screens = QGuiApplication.screens()
        if not screens:
            return
        for screen in screens:
            available = screen.availableGeometry()
            if available.intersects(frame):
                return
        # Reposition to primary screen center
        primary = screens[0].availableGeometry()
        x = primary.x() + (primary.width() - frame.width()) // 2
        y = primary.y() + (primary.height() - frame.height()) // 2
        self.move(x, y)

    def _save_geometry(self):
        try:
            key = "panel_geometry" if self._panel_mode else "normal_geometry"
            self._settings.setValue(key, self.saveGeometry())
        except Exception:
            pass

    # ── Close ─────────────────────────────────────────────────

    def closeEvent(self, event):
        self._save_geometry()

        # Collect all workers and timers for safe shutdown
        workers = []
        timers = []

        try:
            for page in self._pages.values():
                for attr in dir(page):
                    try:
                        obj = getattr(page, attr, None)
                    except Exception:
                        continue
                    try:
                        if isinstance(obj, QTimer) and obj.isActive():
                            timers.append(obj)
                    except Exception:
                        pass
                    try:
                        if hasattr(obj, "isRunning") and obj.isRunning():
                            workers.append(obj)
                    except Exception:
                        pass
        except Exception as e:
            from app.utils.logger import get_logger
            get_logger("ui.main_window").debug(f"Worker/timer collection error: {e}")

        # Safe shutdown
        from app.core.error_boundaries import safe_shutdown_workers, safe_stop_timers
        safe_stop_timers(timers)
        safe_shutdown_workers(workers, timeout_per_worker=1.5)

        # Stop telemetry
        try:
            from app.core.telemetry import telemetry_engine
            telemetry_engine.stop()
        except Exception as e:
            from app.utils.logger import get_logger
            get_logger("ui.main_window").debug(f"Telemetry stop error: {e}")

        # Cleanup GPU
        try:
            from app.system.gpu import gpu_monitor
            gpu_monitor.cleanup()
        except Exception as e:
            from app.utils.logger import get_logger
            get_logger("ui.main_window").debug(f"GPU cleanup error: {e}")

        event.accept()
