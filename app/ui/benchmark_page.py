"""
Benchmark page — run FPS/frame-time benchmarks with results display.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QProgressBar,
    QTextEdit, QHBoxLayout, QSpinBox, QGroupBox, QGridLayout
)
from PySide6.QtCore import Qt, Signal, QThread

from app.core.benchmark import benchmark_engine, BenchmarkConfig, BenchmarkResult
from app.utils.logger import get_logger

logger = get_logger("ui.benchmark_page")


class BenchmarkThread(QThread):
    """Background benchmark thread."""
    progress = Signal(float)
    complete = Signal(object)

    def run(self):
        config = BenchmarkConfig(duration_seconds=30)
        result = benchmark_engine.run_sync(config)
        self.complete.emit(result)


class BenchmarkPage(QWidget):
    """Benchmark page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("BENCHMARK ENGINE")
        header.setStyleSheet("color: #e74c3c; font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        # Config
        config_group = QGroupBox("Configuration")
        config_group.setStyleSheet("QGroupBox { color: #ecf0f1; font-weight: bold; border: 1px solid #34495e; border-radius: 5px; }")
        config_layout = QGridLayout()
        config_layout.addWidget(QLabel("Duration (seconds):"), 0, 0)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(10, 120)
        self.duration_spin.setValue(30)
        config_layout.addWidget(self.duration_spin, 0, 1)
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("""
            QProgressBar { background-color: #2c3e50; border-radius: 4px; }
            QProgressBar::chunk { background-color: #8e44ad; border-radius: 4px; }
        """)
        layout.addWidget(self.progress_bar)

        # Results
        self.results_group = QGroupBox("Results")
        self.results_group.setStyleSheet(config_group.styleSheet())
        results_layout = QGridLayout()
        self.result_labels = {}
        for i, (key, label) in enumerate([
            ("avg_fps", "Average FPS"), ("one_low", "1% Low"),
            ("point_one_low", "0.1% Low"), ("avg_frame_time", "Avg Frame Time"),
            ("frame_variance", "Frame Time Variance"),
            ("spikes", "Frame Spikes"), ("drops", "FPS Drops"),
            ("score", "Performance Score"), ("grade", "Grade"),
        ]):
            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet("color: #95a5a6;")
            val = QLabel("--")
            val.setStyleSheet("color: #ecf0f1; font-weight: bold;")
            results_layout.addWidget(lbl, i, 0)
            results_layout.addWidget(val, i, 1)
            self.result_labels[key] = val
        self.results_group.setLayout(results_layout)
        layout.addWidget(self.results_group)

        # Start button
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("🧪 RUN BENCHMARK")
        self.start_btn.setMinimumHeight(45)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #8e44ad; color: white; font-size: 14px; font-weight: bold;
                border: none; border-radius: 8px; padding: 10px 30px;
            }
            QPushButton:hover { background-color: #7d3c98; }
            QPushButton:disabled { background-color: #555; }
        """)
        self.start_btn.clicked.connect(self._start_benchmark)
        btn_layout.addWidget(self.start_btn)
        layout.addLayout(btn_layout)

        layout.addStretch()

    def _start_benchmark(self):
        self.start_btn.setEnabled(False)
        self._thread = BenchmarkThread()
        self._thread.progress.connect(lambda p: self.progress_bar.setValue(int(p * 100)))
        self._thread.complete.connect(self._on_complete)
        self._thread.start()

    def _on_complete(self, result: BenchmarkResult):
        self.start_btn.setEnabled(True)
        self.progress_bar.setValue(100)

        m = result.metrics
        self.result_labels["avg_fps"].setText(f"{m.avg_fps:.1f}")
        self.result_labels["one_low"].setText(f"{m.one_percent_low:.1f}")
        self.result_labels["point_one_low"].setText(f"{m.point_one_percent_low:.1f}")
        self.result_labels["avg_frame_time"].setText(f"{m.avg_frame_time_ms:.2f} ms")
        self.result_labels["frame_variance"].setText(f"{m.frame_time_variance:.2f}")
        self.result_labels["spikes"].setText(str(m.frame_spikes))
        self.result_labels["drops"].setText(str(m.fps_drops))

        score = result.score
        self.result_labels["score"].setText(f"{score.total_score:.1f}/100")
        self.result_labels["grade"].setText(score.grade)

        # Color code the grade
        grade_colors = {"S": "#2ecc71", "A": "#2ecc71", "B": "#f1c40f", "C": "#f39c12", "D": "#e67e22", "E": "#e74c3c", "F": "#c0392b"}
        color = grade_colors.get(score.grade, "#ecf0f1")
        self.result_labels["grade"].setStyleSheet(f"color: {color}; font-weight: bold; font-size: 18px;")

        logger.info(f"Benchmark complete: {m.avg_fps:.1f} FPS, Score: {score.total_score:.1f} ({score.grade})")
