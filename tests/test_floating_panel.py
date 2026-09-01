"""
Tests for Phase 45 — Floating Gaming Panel UI.
Simplified to avoid timer/worker hangs in offscreen mode.
"""

import pytest
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _make_window():
    """Create a MainWindow and immediately stop all timers/workers."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
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
        assert 380 <= w.width() <= 600
        assert 500 <= w.height() <= 900
        w.close()

    def test_frameless(self):
        from PySide6.QtCore import Qt
        w = _make_window()
        assert int(w.windowFlags()) & Qt.FramelessWindowHint
        w.close()

    def test_always_on_top_default(self):
        from PySide6.QtCore import Qt
        w = _make_window()
        assert int(w.windowFlags()) & Qt.WindowStaysOnTopHint
        assert w._gaming_mode is True
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


class TestGamingMode:
    def test_toggle(self):
        from PySide6.QtCore import Qt
        w = _make_window()
        assert w._gaming_mode is True
        w._toggle_gaming_mode()
        assert w._gaming_mode is False
        assert not (int(w.windowFlags()) & Qt.WindowStaysOnTopHint)
        w._toggle_gaming_mode()
        assert w._gaming_mode is True
        assert int(w.windowFlags()) & Qt.WindowStaysOnTopHint
        w.close()

    def test_button_exists(self):
        w = _make_window()
        assert hasattr(w, "_gm_btn")
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
