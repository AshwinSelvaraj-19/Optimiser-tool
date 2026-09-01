"""
Tests for Phase 46 — Dual-mode Floating Gaming Panel + Normal Window.
"""

import pytest
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _clear_settings():
    from PySide6.QtCore import QSettings
    s = QSettings("HeavenSociety", "Panel")
    for k in ["panel_geometry", "normal_geometry", "panel_mode", "always_on_top", "gaming_mode"]:
        s.remove(k)


def _make_window(panel_mode=True):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    _clear_settings()
    from PySide6.QtCore import QSettings
    s = QSettings("HeavenSociety", "Panel")
    s.setValue("panel_mode", panel_mode)
    from app.ui.main_window import MainWindow
    from PySide6.QtCore import QTimer
    w = MainWindow()
    for page in w._pages.values():
        for attr in dir(page):
            obj = getattr(page, attr, None)
            try:
                if isinstance(obj, QTimer) and obj.isActive():
                    obj.stop()
            except Exception:
                pass
    return w


class TestPanelMode:
    def test_creates_panel(self):
        w = _make_window(panel_mode=True)
        assert w._panel_mode is True
        w.close()

    def test_panel_size(self):
        w = _make_window(panel_mode=True)
        assert 400 <= w.width() <= 520
        assert 500 <= w.height() <= 850
        w.close()

    def test_panel_frameless(self):
        from PySide6.QtCore import Qt
        w = _make_window(panel_mode=True)
        assert int(w.windowFlags()) & Qt.FramelessWindowHint
        w.close()

    def test_panel_has_tabs(self):
        w = _make_window(panel_mode=True)
        assert len(w._tab_buttons) >= 6
        w.close()

    def test_panel_no_sidebar(self):
        w = _make_window(panel_mode=True)
        assert w._sidebar_widget is None
        w.close()


class TestNormalMode:
    def test_creates_normal(self):
        w = _make_window(panel_mode=False)
        assert w._panel_mode is False
        w.close()

    def test_normal_size(self):
        w = _make_window(panel_mode=False)
        assert 700 <= w.width()
        assert 500 <= w.height()
        w.close()

    def test_normal_not_frameless(self):
        from PySide6.QtCore import Qt
        w = _make_window(panel_mode=False)
        assert not (int(w.windowFlags()) & Qt.FramelessWindowHint)
        w.close()

    def test_normal_has_sidebar(self):
        w = _make_window(panel_mode=False)
        assert w._sidebar_widget is not None
        assert len(w._nav_buttons) == 6
        w.close()

    def test_normal_no_tabs(self):
        w = _make_window(panel_mode=False)
        assert len(w._tab_buttons) == 0
        w.close()


class TestModeSwitching:
    def test_panel_to_normal(self):
        from PySide6.QtCore import Qt
        w = _make_window(panel_mode=True)
        assert w._panel_mode is True
        assert int(w.windowFlags()) & Qt.FramelessWindowHint
        w._toggle_mode()
        assert w._panel_mode is False
        assert not (int(w.windowFlags()) & Qt.FramelessWindowHint)
        assert w._sidebar_widget is not None
        w.close()

    def test_normal_to_panel(self):
        from PySide6.QtCore import Qt
        w = _make_window(panel_mode=False)
        assert w._panel_mode is False
        w._toggle_mode()
        assert w._panel_mode is True
        assert int(w.windowFlags()) & Qt.FramelessWindowHint
        assert len(w._tab_buttons) >= 6
        w.close()

    def test_mode_persisted(self):
        from PySide6.QtCore import QSettings
        w = _make_window(panel_mode=True)
        w._toggle_mode()
        s = QSettings("HeavenSociety", "Panel")
        assert s.value("panel_mode", True, type=bool) is False
        w.close()

    def test_page_preserved_across_mode_switch(self):
        w = _make_window(panel_mode=True)
        w._navigate_to("optimize")
        assert "optimize" in w._pages
        w._toggle_mode()
        # After switch, should navigate to the same page
        assert w._current_page_key == "optimize"
        w.close()


class TestAlwaysOnTop:
    def test_default_off(self):
        from PySide6.QtCore import Qt
        w = _make_window()
        assert w._always_on_top is False
        assert not (int(w.windowFlags()) & Qt.WindowStaysOnTopHint)
        w.close()

    def test_toggle(self):
        from PySide6.QtCore import Qt
        w = _make_window()
        w._toggle_always_on_top()
        assert w._always_on_top is True
        assert int(w.windowFlags()) & Qt.WindowStaysOnTopHint
        w._toggle_always_on_top()
        assert w._always_on_top is False
        assert not (int(w.windowFlags()) & Qt.WindowStaysOnTopHint)
        w.close()

    def test_persisted(self):
        from PySide6.QtCore import QSettings
        w = _make_window()
        w._toggle_always_on_top()
        s = QSettings("HeavenSociety", "Panel")
        assert s.value("always_on_top", False, type=bool) is True
        w.close()

    def test_pin_button_exists(self):
        w = _make_window()
        assert hasattr(w, "_pin_btn")
        w.close()


class TestNavigation:
    def test_panel_tab_navigation(self):
        w = _make_window(panel_mode=True)
        w._navigate_to("optimize")
        assert w._current_page_key == "optimize"
        assert "optimize" in w._pages
        w.close()

    def test_sidebar_navigation(self):
        w = _make_window(panel_mode=False)
        w._navigate_to("monitor")
        assert w._current_page_key == "monitor"
        assert "monitor" in w._pages
        w.close()

    def test_lazy_loading(self):
        w = _make_window()
        assert "cleanup" not in w._pages
        w._navigate_to("cleanup")
        assert "cleanup" in w._pages
        w.close()

    def test_page_reuse(self):
        w = _make_window()
        w._navigate_to("tools")
        p1 = w._pages["tools"]
        w._navigate_to("home")
        w._navigate_to("tools")
        assert w._pages["tools"] is p1
        w.close()


class TestGeometryPersistence:
    def test_panel_geometry_saved(self):
        from PySide6.QtCore import QSettings
        w = _make_window(panel_mode=True)
        w.move(100, 200)
        w._save_geometry()
        s = QSettings("HeavenSociety", "Panel")
        assert s.value("panel_geometry") is not None
        w.close()

    def test_normal_geometry_saved(self):
        from PySide6.QtCore import QSettings
        w = _make_window(panel_mode=False)
        w.move(300, 400)
        w._save_geometry()
        s = QSettings("HeavenSociety", "Panel")
        assert s.value("normal_geometry") is not None
        w.close()

    def test_off_screen_recovery(self):
        w = _make_window()
        w.move(-5000, -5000)
        w._ensure_visible_on_screen()
        from PySide6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
        if screens:
            primary = screens[0].availableGeometry()
            frame = w.frameGeometry()
            assert primary.intersects(frame)
        w.close()


class TestPerformance:
    def test_cached_navigation_fast(self):
        import time
        w = _make_window()
        w._navigate_to("optimize")
        t0 = time.perf_counter()
        w._navigate_to("optimize")
        dt = (time.perf_counter() - t0) * 1000
        assert dt < 100, f"Cached nav: {dt:.0f}ms"
        w.close()
