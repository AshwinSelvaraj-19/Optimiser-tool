"""
Heaven Society — TOOLS Page

Benchmark and Diagnostic — compact utility panels.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTextEdit, QProgressBar, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QThread

from app.ui.theme import (
    BG_PANEL, BORDER_LIGHT, BORDER_MEDIUM,
    ACCENT_PRIMARY, ACCENT_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY, TEXT_INVERSE,
    STATUS_OK, STATUS_WARN, STATUS_ERROR, STATUS_MUTED,
    FONT_FAMILY, FONT_MONO,
    FONT_SIZE_SM, FONT_SIZE_XS, FONT_SIZE_MD,
    WEIGHT_BOLD, WEIGHT_SEMIBOLD, WEIGHT_MEDIUM,
    RADIUS_MD, card_style, button_primary_style, button_secondary_style,
    card_title_style,
)
from app.utils.logger import get_logger

logger = get_logger("ui.tools_page")


class BenchmarkThread(QThread):
    """Background benchmark thread."""
    progress = Signal(str)
    complete = Signal(dict)

    def __init__(self, duration: int = 10):
        super().__init__()
        self.duration = duration

    def run(self):
        from app.performance.benchmark_cli import run_benchmark_cli
        report = run_benchmark_cli(duration=self.duration)
        self.complete.emit(report or {})


class DiagnosticThread(QThread):
    """Background diagnostic thread."""
    complete = Signal(str)

    def run(self):
        import io
        import sys
        from contextlib import redirect_stdout

        from main import run_diagnostic

        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                run_diagnostic()
        except Exception as e:
            buf.write(f"\nDiagnostic error: {e}\n")

        self.complete.emit(buf.getvalue())


class ToolsPage(QWidget):
    """Tools page with benchmark and diagnostic."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._benchmark_thread = None
        self._diagnostic_thread = None
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

        title = QLabel("TOOLS")
        title.setStyleSheet(f"""
            color: {ACCENT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 2px;
            border: none;
        """)
        layout.addWidget(title)

        # ── Benchmark Panel ──────────────────────────────────
        bench_frame = QFrame()
        bench_frame.setStyleSheet(f"""
            QFrame {{
                {card_style()}
            }}
        """)
        bench_layout = QVBoxLayout(bench_frame)
        bench_layout.setContentsMargins(10, 8, 10, 8)
        bench_layout.setSpacing(4)

        bench_header = QHBoxLayout()
        bench_title = QLabel("BENCHMARK")
        bench_title.setStyleSheet(card_title_style())
        bench_header.addWidget(bench_title)
        bench_header.addStretch()

        self.bench_btn = QPushButton("START")
        self.bench_btn.setFixedHeight(28)
        self.bench_btn.setCursor(Qt.PointingHandCursor)
        self.bench_btn.setStyleSheet(button_primary_style())
        self.bench_btn.clicked.connect(self._start_benchmark)
        bench_header.addWidget(self.bench_btn)
        bench_layout.addLayout(bench_header)

        self.bench_progress = QProgressBar()
        self.bench_progress.setRange(0, 100)
        self.bench_progress.setValue(0)
        self.bench_progress.setFixedHeight(3)
        self.bench_progress.setTextVisible(False)
        bench_layout.addWidget(self.bench_progress)

        self.bench_status = QLabel("Ready")
        self.bench_status.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        bench_layout.addWidget(self.bench_status)

        # Results area
        self.bench_results = QLabel("")
        self.bench_results.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        self.bench_results.setWordWrap(True)
        bench_layout.addWidget(self.bench_results)

        layout.addWidget(bench_frame)

        # ── Diagnostic Panel ─────────────────────────────────
        diag_frame = QFrame()
        diag_frame.setStyleSheet(f"""
            QFrame {{
                {card_style()}
            }}
        """)
        diag_layout = QVBoxLayout(diag_frame)
        diag_layout.setContentsMargins(10, 8, 10, 8)
        diag_layout.setSpacing(4)

        diag_header = QHBoxLayout()
        diag_title = QLabel("DIAGNOSTIC")
        diag_title.setStyleSheet(card_title_style())
        diag_header.addWidget(diag_title)
        diag_header.addStretch()

        self.diag_btn = QPushButton("RUN")
        self.diag_btn.setFixedHeight(28)
        self.diag_btn.setCursor(Qt.PointingHandCursor)
        self.diag_btn.setStyleSheet(button_secondary_style())
        self.diag_btn.clicked.connect(self._start_diagnostic)
        diag_header.addWidget(self.diag_btn)
        diag_layout.addLayout(diag_header)

        self.diag_text = QTextEdit()
        self.diag_text.setReadOnly(True)
        self.diag_text.setMaximumHeight(160)
        self.diag_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {BG_PANEL};
                color: {TEXT_SECONDARY};
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_XS};
                border: 1px solid {BORDER_LIGHT};
                border-radius: {RADIUS_MD};
                padding: 6px;
            }}
        """)
        diag_layout.addWidget(self.diag_text)

        layout.addWidget(diag_frame)
        layout.addStretch()

    def refresh(self):
        pass

    def _start_benchmark(self):
        self.bench_btn.setEnabled(False)
        self.bench_status.setText("Running benchmark (10s)...")
        self.bench_results.setText("")
        self.bench_progress.setValue(0)

        self._benchmark_thread = BenchmarkThread(duration=10)
        self._benchmark_thread.progress.connect(self._on_bench_progress)
        self._benchmark_thread.complete.connect(self._on_bench_complete)
        self._benchmark_thread.start()

    def _on_bench_progress(self, msg):
        self.bench_status.setText(msg)

    def _on_bench_complete(self, report):
        self.bench_btn.setEnabled(True)
        self.bench_progress.setValue(100)

        if not report:
            self.bench_status.setText("Benchmark failed")
            return

        self.bench_status.setText("Complete")

        fps_data = report.get("fps_metrics", {})
        if fps_data.get("available"):
            lines = [
                f"FPS:      {fps_data.get('avg_fps', 0):.1f}",
                f"1% Low:   {fps_data.get('one_percent_low', 0):.1f}",
                f"0.1% Low: {fps_data.get('point_one_percent_low', 0):.1f}",
                f"Frame:    {fps_data.get('avg_frame_time_ms', 0):.2f} ms",
                f"Spikes:   {fps_data.get('frame_spikes', 0)}",
                f"Samples:  {fps_data.get('sample_count', 0)}",
            ]
            self.bench_results.setText("\n".join(lines))
        else:
            reason = fps_data.get("reason", "No FPS provider available")
            self.bench_results.setText(f"FPS: UNAVAILABLE\n{reason}")

    def _start_diagnostic(self):
        self.diag_btn.setEnabled(False)
        self.diag_text.clear()
        self.diag_text.append("Running diagnostic...")

        self._diagnostic_thread = DiagnosticThread()
        self._diagnostic_thread.complete.connect(self._on_diag_complete)
        self._diagnostic_thread.start()

    def _on_diag_complete(self, output):
        self.diag_btn.setEnabled(True)
        self.diag_text.clear()
        self.diag_text.append(output)
