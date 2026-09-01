"""
Tests for Phase 46 — Floating Gaming Panel UI.
Simplified to avoid timer/worker hangs in offscreen mode.
"""

import pytest
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _clear_settings():
    """Clear persisted settings so tests start fresh."""
    from PySide6.QtCore import QSettings
    s = QSettings("HeavenSociety", "Panel")
    s.remove("geometry")
    s.remove("always_on_top")
    s.remove("gaming_mode")


def _make_window():
    """Create a MainWindow with fresh settings and stop all timers."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    _clear_settings()
    from app.ui.main_window import MainWindow
    from PySide6.QtCore import QTimer
    w = MainWindow()
    # Stop all timers immediately to prevent background work
    for page in w._pages.values():
        for attr in dir(page):
            obj = getattr(page, attr, None)
            try:
                if isinstance(obj, QTimer) and obj.isActive():
                    obj.stop()
            except Exception:
                pass
    return w


class TestWindowCreation:
    def test_creates(self):
        w = _make_window()
        assert w is not None
        w.close()

    def test_compact_size(self):
        w = _make_window()
        assert 480 <= w.width() <= 1200
        assert 500 <= w.height() <= 1000
        w.close()

    def test_frameless(self):
        from PySide6.QtCore import Qt
        w = _make_window()
        assert int(w.windowFlags()) & Qt.FramelessWindowHint
        w.close()

    def test_always_on_top_default_off(self):
        """Always-on-top is OFF by default (persisted as False)."""
        from PySide6.QtCore import Qt
        w = _make_window()
        assert w._always_on_top is False
        assert not (int(w.windowFlags()) & Qt.WindowStaysOnTopHint)
        w.close()

    def test_gaming_mode_default_off(self):
        """Gaming mode is OFF by default."""
        w = _make_window()
        assert w._gaming_mode is False
        w.close()


class TestNavigation:
    def test_sidebar_buttons(self):
        w = _make_window()
        assert len(w._nav_buttons) == 6
        keys = [b.page_key for b in w._nav_buttons]
        assert "home" in keys
        assert "optimize" in keys
        w.close()

    def test_home_initially_created(self):
        w = _make_window()
        assert "home" in w._pages
        w.close()

    def test_lazy_loading(self):
        w = _make_window()
        assert "optimize" not in w._pages
        w._navigate_to("optimize")
        assert "optimize" in w._pages
        w.close()

    def test_page_reuse(self):
        w = _make_window()
        w._navigate_to("optimize")
        p1 = w._pages["optimize"]
        w._navigate_to("home")
        w._navigate_to("optimize")
        assert w._pages["optimize"] is p1
        w.close()


class TestAlwaysOnTop:
    def test_toggle_always_on_top(self):
        from PySide6.QtCore import Qt
        w = _make_window()
        assert w._always_on_top is False
        w._toggle_always_on_top()
        assert w._always_on_top is True
        assert int(w.windowFlags()) & Qt.WindowStaysOnTopHint
        w._toggle_always_on_top()
        assert w._always_on_top is False
        assert not (int(w.windowFlags()) & Qt.WindowStaysOnTopHint)
        w.close()

    def test_pin_button_exists(self):
        w = _make_window()
        assert hasattr(w, "_pin_btn")
        w.close()

    def test_always_on_top_persisted(self):
        """Toggle always-on-top and verify the setting is persisted."""
        from PySide6.QtCore import QSettings
        w = _make_window()
        w._toggle_always_on_top()
        settings = QSettings("HeavenSociety", "Panel")
        assert settings.value("always_on_top", False, type=bool) is True
        w.close()


class TestGamingMode:
    def test_gaming_mode_independent_of_pin(self):
        """Gaming mode does not affect always-on-top state."""
        from PySide6.QtCore import Qt
        w = _make_window()
        # Pin is OFF, gaming mode OFF
        assert w._always_on_top is False
        assert w._gaming_mode is False
        # Toggle gaming mode — pin should remain OFF
        w._toggle_gaming_mode()
        assert w._gaming_mode is True
        assert w._always_on_top is False
        assert not (int(w.windowFlags()) & Qt.WindowStaysOnTopHint)
        w.close()

    def test_gaming_mode_hides_widgets(self):
        """Gaming mode hides non-essential HomePage widgets."""
        w = _make_window()
        # Ensure home page is loaded
        assert "home" in w._pages
        home = w._pages["home"]
        w._toggle_gaming_mode()
        # Stability block should be hidden
        assert home.stability_block.isHidden()
        # Gaming analysis frame should be hidden
        assert home.ga_frame.isHidden()
        w.close()

    def test_gaming_mode_persisted(self):
        from PySide6.QtCore import QSettings
        w = _make_window()
        w._toggle_gaming_mode()
        settings = QSettings("HeavenSociety", "Panel")
        assert settings.value("gaming_mode", False, type=bool) is True
        w.close()

    def test_button_exists(self):
        w = _make_window()
        assert hasattr(w, "_gm_btn")
        w.close()


class TestGeometryPersistence:
    def test_geometry_saved_on_close(self):
        """Geometry is saved to QSettings on close."""
        from PySide6.QtCore import QSettings
        w = _make_window()
        w.move(100, 200)
        w.resize(950, 680)
        w._save_geometry()
        settings = QSettings("HeavenSociety", "Panel")
        assert settings.value("geometry") is not None
        w.close()

    def test_off_screen_recovery(self):
        """Window off-screen gets repositioned to visible area."""
        w = _make_window()
        # Simulate off-screen position
        w.move(-5000, -5000)
        w._ensure_visible_on_screen()
        # After recovery, should be on a visible screen
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
        w._navigate_to("optimize")  # first
        t0 = time.perf_counter()
        w._navigate_to("optimize")  # cached
        dt = (time.perf_counter() - t0) * 1000
        assert dt < 50, f"Cached nav: {dt:.0f}ms"
        w.close()

    def test_no_hardware_scan_on_nav(self):
        from app.core.scanner import hardware_scanner
        w = _make_window()
        original = hardware_scanner.scan
        called = [False]
        def patched(*a, **kw):
            called[0] = True
            return original(*a, **kw)
        hardware_scanner.scan = patched
        w._navigate_to("optimize")
        hardware_scanner.scan = original
        assert not called[0]
        w.close()
