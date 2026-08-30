"""
Heaven Society — OPTIMIZE Page

Real profile-based optimization with snapshot/verify/rollback.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QComboBox,
    QPushButton, QTextEdit, QScrollArea, QProgressBar
)
import time
from PySide6.QtCore import Qt, Signal, QThread, QTimer

from app.ui.theme import (
    BG_PANEL, BORDER_LIGHT, ACCENT_PRIMARY, ACCENT_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY, TEXT_INVERSE,
    STATUS_OK, STATUS_WARN, STATUS_ERROR, STATUS_MUTED,
    FONT_FAMILY, FONT_MONO,
    FONT_SIZE_SM, FONT_SIZE_XS,
    WEIGHT_BOLD, WEIGHT_SEMIBOLD, WEIGHT_MEDIUM,
    RADIUS_MD, card_style, button_primary_style, button_secondary_style,
)
from app.core.profiles import get_all_profiles
from app.core.optimizer import optimizer
from app.performance.benchmark_models import BenchmarkResult, BenchmarkComparison
from app.utils.logger import get_logger

logger = get_logger("ui.optimizer_page")


class OptRow(QFrame):
    """Compact optimization status row with value + status."""

    def __init__(self, name: str, value: str = "", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.NoFrame)
        self.setFixedHeight(32)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_LIGHT};
                border-radius: {RADIUS_MD};
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(8)

        self.name_label = QLabel(name)
        self.name_label.setStyleSheet(f"""
            color: {TEXT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_MEDIUM};
            border: none;
        """)
        layout.addWidget(self.name_label, 1)

        if value:
            self.value_label = QLabel(value)
            self.value_label.setStyleSheet(f"""
                color: {TEXT_SECONDARY};
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_XS};
                border: none;
            """)
            layout.addWidget(self.value_label)

        self.status_label = QLabel("")
        self.status_label.setFixedWidth(110)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_SEMIBOLD};
            border-radius: 3px;
            padding: 2px 4px;
            border: none;
        """)
        layout.addWidget(self.status_label)

    def set_status(self, status: str, color: str = TEXT_TERTIARY):
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"""
            color: {color};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_SEMIBOLD};
            background-color: {color}15;
            border-radius: 3px;
            padding: 2px 4px;
            border: none;
        """)


class ApplyThread(QThread):
    """Background optimization thread."""
    progress = Signal(float, str)
    complete = Signal(object)

    def __init__(self, profile_id: str):
        super().__init__()
        self.profile_id = profile_id

    def run(self):
        optimizer.on_progress(lambda p, m: self.progress.emit(p, m))
        report = optimizer.apply_profile(self.profile_id)
        self.complete.emit(report)


class BenchmarkThread(QThread):
    """Background benchmark thread."""
    progress = Signal(float, str)
    complete = Signal(object)

    def __init__(self, profile_id: str, duration: int = 15):
        super().__init__()
        self.profile_id = profile_id
        self.duration = duration

    def run(self):
        from app.performance.optimize_benchmark import run_optimization_benchmark
        comparison = run_optimization_benchmark(
            profile_id=self.profile_id,
            duration=self.duration,
            progress_callback=lambda p, m: self.progress.emit(p, m),
        )
        self.complete.emit(comparison)


class ABThread(QThread):
    """Background A/B benchmark thread."""
    progress = Signal(float, str)
    complete = Signal(object)

    def __init__(self, profile_id: str, duration: int = 15, runs: int = 3):
        super().__init__()
        self.profile_id = profile_id
        self.duration = duration
        self.runs = runs

    def run(self):
        from app.performance.ab_benchmark import run_ab_benchmark
        ab = run_ab_benchmark(
            profile_id=self.profile_id,
            duration=self.duration,
            runs=self.runs,
            progress_callback=lambda p, m: self.progress.emit(p, m),
        )
        self.complete.emit(ab)


class OptimizerPage(QWidget):
    """Optimize page with profile selection and real optimization."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._opt_rows = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title = QLabel("OPTIMIZE")
        title.setStyleSheet(f"""
            color: {ACCENT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 2px;
            border: none;
        """)
        header.addWidget(title)
        header.addStretch()

        self.profile_combo = QComboBox()
        self.profile_combo.setFixedWidth(160)
        for p in get_all_profiles():
            self.profile_combo.addItem(p.name, p.id)
        self.profile_combo.setCurrentIndex(1)  # Default to GAMING
        header.addWidget(self.profile_combo)
        layout.addLayout(header)

        # Hardware recommendation hint
        self.hw_hint = QLabel("")
        self.hw_hint.setStyleSheet(f"""
            color: {ACCENT_LIGHT};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            border: none;
            padding: 2px 0;
        """)
        self.hw_hint.setVisible(False)
        layout.addWidget(self.hw_hint)

        # Target + status card
        status_frame = QFrame()
        status_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(12, 8, 12, 8)
        status_layout.setSpacing(4)

        # Target info
        self.target_label = QLabel("TARGET")
        self.target_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        status_layout.addWidget(self.target_label)

        self.target_text = QLabel("Detecting...")
        self.target_text.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        self.target_text.setWordWrap(True)
        status_layout.addWidget(self.target_text)

        # Status info
        self.status_label = QLabel("STATUS")
        self.status_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        status_layout.addWidget(self.status_label)

        self.status_text = QLabel("Loading...")
        self.status_text.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        self.status_text.setWordWrap(True)
        status_layout.addWidget(self.status_text)

        layout.addWidget(status_frame)

        # Optimization list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self.opt_container = QWidget()
        self.opt_layout = QVBoxLayout(self.opt_container)
        self.opt_layout.setContentsMargins(0, 0, 0, 0)
        self.opt_layout.setSpacing(3)
        self.opt_layout.addStretch()

        scroll.setWidget(self.opt_container)
        layout.addWidget(scroll, 1)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        layout.addWidget(self.progress_label)

        # Log
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(80)
        self.log_text.setStyleSheet(f"""
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
        layout.addWidget(self.log_text)

        # Windows Gaming section
        self.win_frame = QFrame()
        self.win_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        win_layout = QVBoxLayout(self.win_frame)
        win_layout.setContentsMargins(12, 8, 12, 8)
        win_layout.setSpacing(3)

        win_header = QHBoxLayout()
        win_title = QLabel("WINDOWS GAMING")
        win_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        win_header.addWidget(win_title)
        win_header.addStretch()
        self.win_status_label = QLabel("")
        self.win_status_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            border: none;
        """)
        win_header.addWidget(self.win_status_label)
        win_layout.addLayout(win_header)

        # Windows gaming items (populated dynamically)
        self.win_items_container = QWidget()
        self.win_items_layout = QVBoxLayout(self.win_items_container)
        self.win_items_layout.setContentsMargins(0, 0, 0, 0)
        self.win_items_layout.setSpacing(2)
        win_layout.addWidget(self.win_items_container)

        # Windows apply button
        self.win_apply_btn = QPushButton("APPLY WINDOWS")
        self.win_apply_btn.setFixedHeight(28)
        self.win_apply_btn.setCursor(Qt.PointingHandCursor)
        self.win_apply_btn.setStyleSheet(button_secondary_style())
        self.win_apply_btn.clicked.connect(self._start_windows_optimize)
        win_layout.addWidget(self.win_apply_btn)

        layout.addWidget(self.win_frame)

        # Benchmark before/after section (compact)
        bench_frame = QFrame()
        bench_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        bench_layout = QVBoxLayout(bench_frame)
        bench_layout.setContentsMargins(12, 8, 12, 8)
        bench_layout.setSpacing(4)

        bench_header = QHBoxLayout()
        bench_title = QLabel("BENCHMARK")
        bench_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        bench_header.addWidget(bench_title)
        bench_header.addStretch()

        self.bench_result_label = QLabel("")
        self.bench_result_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            border: none;
        """)
        bench_header.addWidget(self.bench_result_label)
        bench_layout.addLayout(bench_header)

        # Confidence label
        self.bench_confidence = QLabel("")
        self.bench_confidence.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        bench_layout.addWidget(self.bench_confidence)

        # Before / After grid
        bench_grid = QHBoxLayout()
        bench_grid.setSpacing(12)

        # Before
        before_col = QVBoxLayout()
        before_col.setSpacing(2)
        before_label = QLabel("BEFORE")
        before_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; font-weight: {WEIGHT_SEMIBOLD}; border: none;")
        before_col.addWidget(before_label)
        self.bench_before_fps = QLabel("--")
        self.bench_before_fps.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        before_col.addWidget(self.bench_before_fps)
        self.bench_before_1low = QLabel("--")
        self.bench_before_1low.setStyleSheet(f"color: {TEXT_SECONDARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_XS}; border: none;")
        before_col.addWidget(self.bench_before_1low)
        self.bench_before_ft = QLabel("--")
        self.bench_before_ft.setStyleSheet(f"color: {TEXT_SECONDARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_XS}; border: none;")
        before_col.addWidget(self.bench_before_ft)
        bench_grid.addLayout(before_col, 1)

        # After
        after_col = QVBoxLayout()
        after_col.setSpacing(2)
        after_label = QLabel("AFTER")
        after_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; font-weight: {WEIGHT_SEMIBOLD}; border: none;")
        after_col.addWidget(after_label)
        self.bench_after_fps = QLabel("--")
        self.bench_after_fps.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        after_col.addWidget(self.bench_after_fps)
        self.bench_after_1low = QLabel("--")
        self.bench_after_1low.setStyleSheet(f"color: {TEXT_SECONDARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_XS}; border: none;")
        after_col.addWidget(self.bench_after_1low)
        self.bench_after_ft = QLabel("--")
        self.bench_after_ft.setStyleSheet(f"color: {TEXT_SECONDARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_XS}; border: none;")
        after_col.addWidget(self.bench_after_ft)
        bench_grid.addLayout(after_col, 1)

        bench_layout.addLayout(bench_grid)
        layout.addWidget(bench_frame)

        # Resource section
        self.resource_frame = QFrame()
        self.resource_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        res_layout = QVBoxLayout(self.resource_frame)
        res_layout.setContentsMargins(12, 8, 12, 8)
        res_layout.setSpacing(3)

        res_header = QHBoxLayout()
        res_title = QLabel("RESOURCES")
        res_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        res_header.addWidget(res_title)
        res_header.addStretch()
        self.res_bottleneck_label = QLabel("")
        self.res_bottleneck_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        res_header.addWidget(self.res_bottleneck_label)
        res_layout.addLayout(res_header)

        # Resource metrics grid
        res_grid = QHBoxLayout()
        res_grid.setSpacing(6)

        self.res_ram_label = QLabel("RAM")
        self.res_ram_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.res_emu_cpu_label = QLabel("EMU CPU")
        self.res_emu_cpu_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.res_emu_ram_label = QLabel("EMU RAM")
        self.res_emu_ram_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.res_gpu_label = QLabel("GPU")
        self.res_gpu_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")

        for lbl in [self.res_ram_label, self.res_emu_cpu_label, self.res_emu_ram_label, self.res_gpu_label]:
            res_grid.addWidget(lbl)
        res_layout.addLayout(res_grid)

        # Resource values grid
        res_vals = QHBoxLayout()
        res_vals.setSpacing(6)

        self.res_ram_val = QLabel("--")
        self.res_ram_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.res_emu_cpu_val = QLabel("--")
        self.res_emu_cpu_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.res_emu_ram_val = QLabel("--")
        self.res_emu_ram_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.res_gpu_val = QLabel("--")
        self.res_gpu_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")

        for lbl in [self.res_ram_val, self.res_emu_cpu_val, self.res_emu_ram_val, self.res_gpu_val]:
            res_vals.addWidget(lbl)
        res_layout.addLayout(res_vals)

        # Recommendation text
        self.res_rec_label = QLabel("")
        self.res_rec_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            border: none;
        """)
        self.res_rec_label.setWordWrap(True)
        res_layout.addWidget(self.res_rec_label)

        layout.addWidget(self.resource_frame)

        # Background load section
        self.bg_frame = QFrame()
        self.bg_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        bg_layout = QVBoxLayout(self.bg_frame)
        bg_layout.setContentsMargins(12, 8, 12, 8)
        bg_layout.setSpacing(3)

        bg_header = QHBoxLayout()
        bg_title = QLabel("BACKGROUND LOAD")
        bg_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        bg_header.addWidget(bg_title)
        bg_header.addStretch()
        self.bg_impact_label = QLabel("")
        self.bg_impact_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        bg_header.addWidget(self.bg_impact_label)
        bg_layout.addLayout(bg_header)

        # Competition metrics
        bg_grid = QHBoxLayout()
        bg_grid.setSpacing(6)

        self.bg_cpu_label = QLabel("CPU COMP")
        self.bg_cpu_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.bg_ram_label = QLabel("RAM COMP")
        self.bg_ram_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.bg_disk_label = QLabel("DISK COMP")
        self.bg_disk_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")

        for lbl in [self.bg_cpu_label, self.bg_ram_label, self.bg_disk_label]:
            bg_grid.addWidget(lbl)
        bg_layout.addLayout(bg_grid)

        bg_vals = QHBoxLayout()
        bg_vals.setSpacing(6)

        self.bg_cpu_val = QLabel("--")
        self.bg_cpu_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.bg_ram_val = QLabel("--")
        self.bg_ram_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.bg_disk_val = QLabel("--")
        self.bg_disk_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")

        for lbl in [self.bg_cpu_val, self.bg_ram_val, self.bg_disk_val]:
            bg_vals.addWidget(lbl)
        bg_layout.addLayout(bg_vals)

        # Recommendation text
        self.bg_rec_label = QLabel("")
        self.bg_rec_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            border: none;
        """)
        self.bg_rec_label.setWordWrap(True)
        bg_layout.addWidget(self.bg_rec_label)

        layout.addWidget(self.bg_frame)

        # Memory section
        self.mem_frame = QFrame()
        self.mem_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        mem_layout = QVBoxLayout(self.mem_frame)
        mem_layout.setContentsMargins(12, 8, 12, 8)
        mem_layout.setSpacing(3)

        mem_header = QHBoxLayout()
        mem_title = QLabel("MEMORY")
        mem_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        mem_header.addWidget(mem_title)
        mem_header.addStretch()
        self.mem_pressure_label = QLabel("")
        self.mem_pressure_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        mem_header.addWidget(self.mem_pressure_label)
        mem_layout.addLayout(mem_header)

        # Memory metrics grid
        mem_grid = QHBoxLayout()
        mem_grid.setSpacing(6)

        self.mem_avail_label = QLabel("AVAIL")
        self.mem_avail_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.mem_used_label = QLabel("USED")
        self.mem_used_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.mem_emu_label = QLabel("EMU RAM")
        self.mem_emu_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.mem_top_label = QLabel("TOP USER")
        self.mem_top_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")

        for lbl in [self.mem_avail_label, self.mem_used_label, self.mem_emu_label, self.mem_top_label]:
            mem_grid.addWidget(lbl)
        mem_layout.addLayout(mem_grid)

        mem_vals = QHBoxLayout()
        mem_vals.setSpacing(6)

        self.mem_avail_val = QLabel("--")
        self.mem_avail_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.mem_used_val = QLabel("--")
        self.mem_used_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.mem_emu_val = QLabel("--")
        self.mem_emu_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.mem_top_val = QLabel("--")
        self.mem_top_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")

        for lbl in [self.mem_avail_val, self.mem_used_val, self.mem_emu_val, self.mem_top_val]:
            mem_vals.addWidget(lbl)
        mem_layout.addLayout(mem_vals)

        # Recommendation text
        self.mem_rec_label = QLabel("")
        self.mem_rec_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            border: none;
        """)
        self.mem_rec_label.setWordWrap(True)
        mem_layout.addWidget(self.mem_rec_label)

        layout.addWidget(self.mem_frame)

        # Startup section
        self.startup_frame = QFrame()
        self.startup_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        startup_layout = QVBoxLayout(self.startup_frame)
        startup_layout.setContentsMargins(12, 8, 12, 8)
        startup_layout.setSpacing(3)

        startup_header = QHBoxLayout()
        startup_title = QLabel("STARTUP")
        startup_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        startup_header.addWidget(startup_title)
        startup_header.addStretch()
        self.startup_count_label = QLabel("")
        self.startup_count_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        startup_header.addWidget(self.startup_count_label)
        startup_layout.addLayout(startup_header)

        # Startup metrics
        startup_grid = QHBoxLayout()
        startup_grid.setSpacing(6)

        self.startup_total_label = QLabel("TOTAL")
        self.startup_total_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.startup_optional_label = QLabel("OPTIONAL")
        self.startup_optional_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.startup_ram_label = QLabel("OPT RAM")
        self.startup_ram_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")

        for lbl in [self.startup_total_label, self.startup_optional_label, self.startup_ram_label]:
            startup_grid.addWidget(lbl)
        startup_layout.addLayout(startup_grid)

        startup_vals = QHBoxLayout()
        startup_vals.setSpacing(6)

        self.startup_total_val = QLabel("--")
        self.startup_total_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.startup_optional_val = QLabel("--")
        self.startup_optional_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.startup_ram_val = QLabel("--")
        self.startup_ram_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")

        for lbl in [self.startup_total_val, self.startup_optional_val, self.startup_ram_val]:
            startup_vals.addWidget(lbl)
        startup_layout.addLayout(startup_vals)

        # Recommendation text
        self.startup_rec_label = QLabel("")
        self.startup_rec_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            border: none;
        """)
        self.startup_rec_label.setWordWrap(True)
        startup_layout.addWidget(self.startup_rec_label)

        layout.addWidget(self.startup_frame)

        # ── TELEMETRY ──
        self.telemetry_frame = QFrame()
        self.telemetry_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        telem_layout = QVBoxLayout(self.telemetry_frame)
        telem_layout.setContentsMargins(12, 8, 12, 8)
        telem_layout.setSpacing(3)

        telem_header = QHBoxLayout()
        telem_title = QLabel("TELEMETRY")
        telem_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        telem_header.addWidget(telem_title)
        telem_header.addStretch()
        self.telemetry_status_label = QLabel("--")
        self.telemetry_status_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        telem_header.addWidget(self.telemetry_status_label)
        telem_layout.addLayout(telem_header)

        telem_grid = QHBoxLayout()
        telem_grid.setSpacing(6)

        self.telem_fps_label = QLabel("FPS")
        self.telem_fps_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.telem_cpu_label = QLabel("CPU")
        self.telem_cpu_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.telem_gpu_label = QLabel("GPU")
        self.telem_gpu_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.telem_ram_label = QLabel("RAM")
        self.telem_ram_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")

        for lbl in [self.telem_fps_label, self.telem_cpu_label, self.telem_gpu_label, self.telem_ram_label]:
            telem_grid.addWidget(lbl)
        telem_layout.addLayout(telem_grid)

        telem_vals = QHBoxLayout()
        telem_vals.setSpacing(6)

        self.telem_fps_val = QLabel("--")
        self.telem_fps_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.telem_cpu_val = QLabel("--")
        self.telem_cpu_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.telem_gpu_val = QLabel("--")
        self.telem_gpu_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.telem_ram_val = QLabel("--")
        self.telem_ram_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")

        for lbl in [self.telem_fps_val, self.telem_cpu_val, self.telem_gpu_val, self.telem_ram_val]:
            telem_vals.addWidget(lbl)
        telem_layout.addLayout(telem_vals)

        # Bottleneck line
        self.telem_bottleneck_label = QLabel("")
        self.telem_bottleneck_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            border: none;
        """)
        telem_layout.addWidget(self.telem_bottleneck_label)

        layout.addWidget(self.telemetry_frame)

        # ── RECOMMENDATIONS ──
        self.rec_frame = QFrame()
        self.rec_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        rec_layout = QVBoxLayout(self.rec_frame)
        rec_layout.setContentsMargins(12, 8, 12, 8)
        rec_layout.setSpacing(3)

        rec_header = QHBoxLayout()
        rec_title = QLabel("RECOMMENDATIONS")
        rec_title.setStyleSheet(f"""
            color: {TEXT_PRIMARY}; font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;
        """)
        rec_header.addWidget(rec_title)
        rec_header.addStretch()
        self.rec_quality_label = QLabel("")
        self.rec_quality_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        rec_header.addWidget(self.rec_quality_label)
        rec_layout.addLayout(rec_header)

        self.rec_bottleneck_label = QLabel("Bottleneck: —")
        self.rec_bottleneck_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        rec_layout.addWidget(self.rec_bottleneck_label)

        self.rec_top_label = QLabel("Top: —")
        self.rec_top_label.setWordWrap(True)
        self.rec_top_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        rec_layout.addWidget(self.rec_top_label)

        self.rec_detail_label = QLabel("")
        self.rec_detail_label.setWordWrap(True)
        self.rec_detail_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        rec_layout.addWidget(self.rec_detail_label)

        layout.addWidget(self.rec_frame)

        # ── ADAPTIVE OPTIMIZATION ──
        self.adaptive_frame = QFrame()
        self.adaptive_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        adapt_layout = QVBoxLayout(self.adaptive_frame)
        adapt_layout.setContentsMargins(12, 8, 12, 8)
        adapt_layout.setSpacing(3)

        adapt_header = QHBoxLayout()
        adapt_title = QLabel("ADAPTIVE OPTIMIZATION")
        adapt_title.setStyleSheet(f"""
            color: {TEXT_PRIMARY}; font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;
        """)
        adapt_header.addWidget(adapt_title)
        adapt_header.addStretch()
        self.adaptive_state_label = QLabel("")
        self.adaptive_state_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        adapt_header.addWidget(self.adaptive_state_label)
        adapt_layout.addLayout(adapt_header)

        self.adaptive_profile_label = QLabel("Profile: —")
        self.adaptive_profile_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        adapt_layout.addWidget(self.adaptive_profile_label)

        self.adaptive_action_label = QLabel("Top: —")
        self.adaptive_action_label.setWordWrap(True)
        self.adaptive_action_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        adapt_layout.addWidget(self.adaptive_action_label)

        layout.addWidget(self.adaptive_frame)

        # ── INPUT & GAMEPLAY ──
        self.input_frame = QFrame()
        self.input_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        input_layout = QVBoxLayout(self.input_frame)
        input_layout.setContentsMargins(12, 8, 12, 8)
        input_layout.setSpacing(3)

        input_header = QHBoxLayout()
        input_title = QLabel("INPUT & GAMEPLAY")
        input_title.setStyleSheet(f"""
            color: {TEXT_PRIMARY}; font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;
        """)
        input_header.addWidget(input_title)
        input_header.addStretch()
        self.input_score_label = QLabel("")
        self.input_score_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        input_header.addWidget(self.input_score_label)
        input_layout.addLayout(input_header)

        self.input_condition_label = QLabel("Condition: —")
        self.input_condition_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        input_layout.addWidget(self.input_condition_label)

        self.input_detail_label = QLabel("")
        self.input_detail_label.setWordWrap(True)
        self.input_detail_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        input_layout.addWidget(self.input_detail_label)

        self.input_rec_label = QLabel("")
        self.input_rec_label.setWordWrap(True)
        self.input_rec_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        input_layout.addWidget(self.input_rec_label)

        layout.addWidget(self.input_frame)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.optimize_btn = QPushButton("APPLY")
        self.optimize_btn.setFixedHeight(34)
        self.optimize_btn.setCursor(Qt.PointingHandCursor)
        self.optimize_btn.setStyleSheet(button_primary_style())
        self.optimize_btn.clicked.connect(self._start_optimization)
        btn_layout.addWidget(self.optimize_btn)

        self.benchmark_btn = QPushButton("BENCHMARK")
        self.benchmark_btn.setFixedHeight(34)
        self.benchmark_btn.setCursor(Qt.PointingHandCursor)
        self.benchmark_btn.setStyleSheet(button_secondary_style())
        self.benchmark_btn.clicked.connect(self._start_benchmark)
        btn_layout.addWidget(self.benchmark_btn)

        self.ab_btn = QPushButton("A/B TEST")
        self.ab_btn.setFixedHeight(34)
        self.ab_btn.setCursor(Qt.PointingHandCursor)
        self.ab_btn.setStyleSheet(button_secondary_style())
        self.ab_btn.clicked.connect(self._start_ab)
        btn_layout.addWidget(self.ab_btn)

        self.validate_btn = QPushButton("VALIDATE")
        self.validate_btn.setFixedHeight(34)
        self.validate_btn.setCursor(Qt.PointingHandCursor)
        self.validate_btn.setStyleSheet(button_secondary_style())
        self.validate_btn.clicked.connect(self._start_validation)
        btn_layout.addWidget(self.validate_btn)

        self.restore_btn = QPushButton("RESTORE")
        self.restore_btn.setFixedHeight(34)
        self.restore_btn.setCursor(Qt.PointingHandCursor)
        self.restore_btn.setStyleSheet(button_secondary_style())
        self.restore_btn.clicked.connect(self._restore)
        btn_layout.addWidget(self.restore_btn)

        self.report_btn = QPushButton("EXPORT REPORT")
        self.report_btn.setFixedHeight(34)
        self.report_btn.setCursor(Qt.PointingHandCursor)
        self.report_btn.setStyleSheet(button_secondary_style())
        self.report_btn.clicked.connect(self._export_report)
        btn_layout.addWidget(self.report_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Session controls
        session_frame = QFrame()
        session_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        session_layout = QHBoxLayout(session_frame)
        session_layout.setContentsMargins(12, 4, 12, 4)
        session_layout.setSpacing(8)

        session_title = QLabel("SESSION")
        session_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS}; font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px; border: none;
        """)
        session_layout.addWidget(session_title)

        self.session_status = QLabel("IDLE")
        self.session_status.setStyleSheet(f"""
            color: {STATUS_MUTED}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        session_layout.addWidget(self.session_status)

        self.session_timer = QLabel("")
        self.session_timer.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        session_layout.addWidget(self.session_timer)

        session_layout.addStretch()

        self.session_start_btn = QPushButton("START")
        self.session_start_btn.setFixedHeight(28)
        self.session_start_btn.setFixedWidth(70)
        self.session_start_btn.setCursor(Qt.PointingHandCursor)
        self.session_start_btn.setStyleSheet(button_primary_style())
        self.session_start_btn.clicked.connect(self._start_session)
        session_layout.addWidget(self.session_start_btn)

        self.session_stop_btn = QPushButton("STOP")
        self.session_stop_btn.setFixedHeight(28)
        self.session_stop_btn.setFixedWidth(70)
        self.session_stop_btn.setCursor(Qt.PointingHandCursor)
        self.session_stop_btn.setStyleSheet(button_secondary_style())
        self.session_stop_btn.setEnabled(False)
        self.session_stop_btn.clicked.connect(self._stop_session)
        session_layout.addWidget(self.session_stop_btn)

        self.session_restore_btn = QPushButton("RESTORE")
        self.session_restore_btn.setFixedHeight(28)
        self.session_restore_btn.setFixedWidth(70)
        self.session_restore_btn.setCursor(Qt.PointingHandCursor)
        self.session_restore_btn.setStyleSheet(button_secondary_style())
        self.session_restore_btn.setEnabled(False)
        self.session_restore_btn.clicked.connect(self._restore_session)
        session_layout.addWidget(self.session_restore_btn)

        layout.addWidget(session_frame)

    def refresh(self):
        self._load_status()
        self._load_windows_status()
        self._load_resource_status()
        self._load_background_status()
        self._load_memory_status()
        self._load_startup_status()
        self._load_telemetry_status()
        self._load_recommendations()
        self._load_adaptive_status()
        self._load_input_status()

    def _load_status(self):
        """Load current optimization status with live target detection."""
        try:
            status = optimizer.get_current_status()
            admin = status.get("admin", False)
            target_name = status.get("target_name", "")
            target_pid = status.get("target_pid", 0)

            # Update target display
            if target_name and target_pid:
                # Get detailed emulator info
                detail = ""
                try:
                    from app.core.emulator_controller import emulator_controller
                    target = emulator_controller.detect_target()
                    if target:
                        detail = (
                            f"{target.name} \u2022 PID {target.pid}\n"
                            f"Priority: {target.priority_name} \u2022 CPUs: {target.affinity_cpus}/{target.total_cpus}\n"
                            f"CPU: {target.cpu_percent:.0f}% \u2022 RAM: {target.memory_mb:.0f}MB"
                        )
                    else:
                        detail = f"{target_name} \u2022 PID {target_pid}"
                except Exception:
                    detail = f"{target_name} \u2022 PID {target_pid}"

                self.target_text.setText(detail)
                self.target_text.setStyleSheet(f"""
                    color: {STATUS_OK};
                    font-family: {FONT_MONO};
                    font-size: {FONT_SIZE_XS};
                    border: none;
                """)
            else:
                self.target_text.setText("No emulator detected")
                self.target_text.setStyleSheet(f"""
                    color: {TEXT_TERTIARY};
                    font-family: {FONT_MONO};
                    font-size: {FONT_SIZE_XS};
                    border: none;
                """)

            # Update status
            busy = status.get("busy", False)
            operation = status.get("operation", "")
            if busy:
                self.status_text.setText(
                    f"Admin: {'YES' if admin else 'NO'} \u2022 {operation}..."
                )
            else:
                self.status_text.setText(
                    f"Admin: {'YES' if admin else 'NO'}\n"
                    f"Optimizations: {len(status.get('optimizations', []))}"
                )

            # Hardware recommendation
            try:
                from app.core.hardware_profile import analyze_hardware_profile
                prof = analyze_hardware_profile()
                rec_name = prof.recommended_profile.value.upper()
                self.hw_hint.setText(
                    f"Hardware: {prof.system_tier.value.upper()} \u2022 Recommended: {rec_name}"
                )
                self.hw_hint.setVisible(True)
            except Exception:
                self.hw_hint.setVisible(False)

            # Clear existing rows
            while self.opt_layout.count() > 1:
                item = self.opt_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._opt_rows.clear()

            # Add optimization rows
            for opt in status.get("optimizations", []):
                row = OptRow(opt["name"], opt.get("current_value", ""))
                s = opt.get("status", "PENDING")
                if s == "ALREADY OPTIMAL":
                    row.set_status("ALREADY OPTIMAL", STATUS_OK)
                elif s == "OPTIMIZABLE":
                    row.set_status("OPTIMIZABLE", STATUS_WARN)
                elif s == "NOT APPLICABLE":
                    row.set_status("NOT APPLICABLE", STATUS_MUTED)
                elif s == "REQUIRES ADMIN":
                    row.set_status("REQUIRES ADMIN", STATUS_WARN)
                elif s == "RECOMMENDATION ONLY":
                    row.set_status("RECOMMENDATION", STATUS_MUTED)
                else:
                    row.set_status(s, STATUS_MUTED)

                self._opt_rows[opt["id"]] = row
                self.opt_layout.insertWidget(self.opt_layout.count() - 1, row)

        except Exception as e:
            logger.debug(f"Status load: {e}")

    def _start_optimization(self):
        profile_id = self.profile_combo.currentData()
        self.optimize_btn.setEnabled(False)
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._log(f"Starting {profile_id} profile...")

        self._thread = ApplyThread(profile_id)
        self._thread.progress.connect(self._on_progress)
        self._thread.complete.connect(self._on_complete)
        self._thread.start()

    def _on_progress(self, pct, msg):
        self.progress_bar.setValue(int(pct * 100))
        self.progress_label.setText(msg)

    def _on_complete(self, report):
        self.optimize_btn.setEnabled(True)
        self.progress_bar.setValue(100)

        # Show structured result
        self._log(f"\n{report.profile_name} — Result:")
        self._log(
            f"  Applied: {report.applied_count}  "
            f"Optimal: {report.already_optimal_count}  "
            f"Admin Required: {report.requires_admin_count}  "
            f"Failed: {report.failed_count}"
        )

        for r in report.results:
            icon = {
                "APPLIED": "+",
                "ALREADY_OPTIMAL": "=",
                "REQUIRES_ADMIN": "!",
                "RECOMMENDATION_ONLY": "~",
                "FAILED": "x",
                "NOT_APPLICABLE": "-",
                "SKIPPED": "?",
            }.get(r.status, "?")

            self._log(f"  [{icon}] {r.name}: {r.status} — {r.message}")

            # Update UI row
            if r.opt_id in self._opt_rows:
                row = self._opt_rows[r.opt_id]
                color_map = {
                    "APPLIED": STATUS_OK,
                    "ALREADY_OPTIMAL": STATUS_OK,
                    "REQUIRES_ADMIN": STATUS_WARN,
                    "RECOMMENDATION_ONLY": STATUS_MUTED,
                    "FAILED": STATUS_ERROR,
                    "NOT_APPLICABLE": STATUS_MUTED,
                }
                row.set_status(r.status, color_map.get(r.status, STATUS_MUTED))

        # Show session result summary
        if report.session:
            s = report.session
            self._log(f"\nLAST RESULT")
            self._log(f"  Applied:      {s.applied_count}")
            self._log(f"  Optimal:      {s.optimal_count}")
            self._log(f"  Admin:        {s.admin_count}")
            self._log(f"  Failed:       {s.failed_count}")
            self._log(f"  Review:       {s.review_count}")

        # Refresh live state after optimization
        self._load_status()

    def _start_benchmark(self):
        """Start the before/after optimization benchmark."""
        profile_id = self.profile_combo.currentData()
        self.benchmark_btn.setEnabled(False)
        self.optimize_btn.setEnabled(False)
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._log(f"Starting benchmark ({profile_id})...")

        self._bench_thread = BenchmarkThread(profile_id, duration=15)
        self._bench_thread.progress.connect(self._on_progress)
        self._bench_thread.complete.connect(self._on_benchmark_complete)
        self._bench_thread.start()

    def _on_benchmark_complete(self, comparison):
        """Handle benchmark completion."""
        self.benchmark_btn.setEnabled(True)
        self.optimize_btn.setEnabled(True)
        self.progress_bar.setValue(100)

        b = comparison.before
        a = comparison.after

        # Update before labels
        if b.is_valid:
            self.bench_before_fps.setText(f"FPS {b.present_fps:.0f}")
            self.bench_before_1low.setText(f"1% Low {b.one_percent_low:.0f}")
            self.bench_before_ft.setText(f"Frame {b.average_frame_time:.1f}ms")
        else:
            self.bench_before_fps.setText("FPS --")
            self.bench_before_1low.setText("")
            self.bench_before_ft.setText("")

        # Update after labels
        if a.is_valid:
            self.bench_after_fps.setText(f"FPS {a.present_fps:.0f}")
            self.bench_after_1low.setText(f"1% Low {a.one_percent_low:.0f}")
            self.bench_after_ft.setText(f"Frame {a.average_frame_time:.1f}ms")
        else:
            self.bench_after_fps.setText("FPS --")
            self.bench_after_1low.setText("")
            self.bench_after_ft.setText("")

        # Result label
        result_colors = {
            "IMPROVED": STATUS_OK,
            "DEGRADED": STATUS_ERROR,
            "UNCHANGED": STATUS_MUTED,
            "INCONCLUSIVE": STATUS_WARN,
        }
        color = result_colors.get(comparison.result, STATUS_MUTED)
        self.bench_result_label.setText(comparison.result)
        self.bench_result_label.setStyleSheet(f"""
            color: {color};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            border: none;
        """)

        # Log details
        self._log(f"\nBenchmark Result: {comparison.result}")
        if comparison.fps_percent is not None:
            sign = "+" if comparison.fps_delta >= 0 else ""
            self._log(f"  FPS: {sign}{comparison.fps_delta:.1f} ({sign}{comparison.fps_percent:.1f}%)")
        if comparison.one_percent_low_delta is not None:
            sign = "+" if comparison.one_percent_low_delta >= 0 else ""
            self._log(f"  1% Low: {sign}{comparison.one_percent_low_delta:.1f} ({sign}{comparison.one_percent_low_percent:.1f}%)")
        if comparison.frame_time_delta is not None:
            sign = "+" if comparison.frame_time_delta >= 0 else ""
            self._log(f"  Frame Time: {sign}{comparison.frame_time_delta:.2f}ms")

        if comparison.optimizations_applied:
            self._log(f"  Applied: {', '.join(comparison.optimizations_applied)}")

    def _start_ab(self):
        """Start A/B benchmark with repeated captures."""
        profile_id = self.profile_combo.currentData()
        self.ab_btn.setEnabled(False)
        self.benchmark_btn.setEnabled(False)
        self.optimize_btn.setEnabled(False)
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._log(f"Starting A/B test ({profile_id})...")

        self._ab_thread = ABThread(profile_id, duration=15, runs=3)
        self._ab_thread.progress.connect(self._on_progress)
        self._ab_thread.complete.connect(self._on_ab_complete)
        self._ab_thread.start()

    def _on_ab_complete(self, ab):
        """Handle A/B benchmark completion."""
        self.ab_btn.setEnabled(True)
        self.benchmark_btn.setEnabled(True)
        self.optimize_btn.setEnabled(True)
        self.progress_bar.setValue(100)

        # Update before/after from medians
        if ab.baseline_stats and ab.optimized_stats:
            bl_fps = ab.baseline_stats.get("present_fps")
            op_fps = ab.optimized_stats.get("present_fps")
            if bl_fps and bl_fps.median:
                self.bench_before_fps.setText(f"FPS {bl_fps.median:.0f}")
            else:
                self.bench_before_fps.setText("FPS --")
            if op_fps and op_fps.median:
                self.bench_after_fps.setText(f"FPS {op_fps.median:.0f}")
            else:
                self.bench_after_fps.setText("FPS --")

            bl_low = ab.baseline_stats.get("one_percent_low")
            op_low = ab.optimized_stats.get("one_percent_low")
            self.bench_before_1low.setText(f"1% Low {bl_low.median:.0f}" if bl_low and bl_low.median else "")
            self.bench_after_1low.setText(f"1% Low {op_low.median:.0f}" if op_low and op_low.median else "")

            bl_ft = ab.baseline_stats.get("average_frame_time")
            op_ft = ab.optimized_stats.get("average_frame_time")
            self.bench_before_ft.setText(f"Frame {bl_ft.median:.1f}ms" if bl_ft and bl_ft.median else "")
            self.bench_after_ft.setText(f"Frame {op_ft.median:.1f}ms" if op_ft and op_ft.median else "")

        # Result
        result_colors = {
            "IMPROVED": STATUS_OK,
            "DEGRADED": STATUS_ERROR,
            "UNCHANGED": STATUS_MUTED,
            "INCONCLUSIVE": STATUS_WARN,
        }
        color = result_colors.get(ab.result, STATUS_MUTED)
        self.bench_result_label.setText(ab.result)
        self.bench_result_label.setStyleSheet(f"""
            color: {color}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)

        # Confidence
        conf_colors = {
            "HIGH": STATUS_OK,
            "MODERATE": STATUS_WARN,
            "LOW": STATUS_ERROR,
            "INCONCLUSIVE": STATUS_MUTED,
        }
        conf_color = conf_colors.get(ab.confidence, STATUS_MUTED)
        bl_v = ab.baseline.valid_count if ab.baseline else 0
        op_v = ab.optimized.valid_count if ab.optimized else 0
        self.bench_confidence.setText(f"Confidence: {ab.confidence}  Valid: {bl_v}+{op_v}")
        self.bench_confidence.setStyleSheet(f"""
            color: {conf_color}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            border: none;
        """)

        # Log details
        self._log(f"\nA/B Result: {ab.result} (Confidence: {ab.confidence})")
        self._log(f"  Valid runs: baseline {bl_v}, optimized {op_v}")
        if ab.fps_percent is not None:
            sign = "+" if ab.fps_delta >= 0 else ""
            self._log(f"  FPS: {sign}{ab.fps_delta:.1f} ({sign}{ab.fps_percent:.1f}%)")
        if ab.one_low_percent is not None:
            sign = "+" if ab.one_low_delta >= 0 else ""
            self._log(f"  1% Low: {sign}{ab.one_low_delta:.1f} ({sign}{ab.one_low_percent:.1f}%)")
        if ab.frame_time_delta is not None:
            sign = "+" if ab.frame_time_delta >= 0 else ""
            self._log(f"  Frame Time: {sign}{ab.frame_time_delta:.2f}ms")
        if ab.optimizations_applied:
            self._log(f"  Applied: {', '.join(ab.optimizations_applied)}")

    def _start_validation(self):
        """Start optimization evidence validation."""
        profile_id = self.profile_combo.currentData()
        self.validate_btn.setEnabled(False)
        self.optimize_btn.setEnabled(False)
        self.ab_btn.setEnabled(False)
        self.benchmark_btn.setEnabled(False)
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._log(f"Starting validation ({profile_id})...")

        class ValidationThread(QThread):
            progress = Signal(float, str)
            complete = Signal(object)

            def __init__(self, pid):
                super().__init__()
                self.pid = pid

            def run(self):
                from app.core.optimization_evidence import optimization_evidence_engine
                from app.core.profiles import get_profile

                profile = get_profile(self.pid)
                if not profile:
                    self.complete.emit(None)
                    return

                opt_ids = [po.opt_id for po in profile.optimizations]
                opt_names = {po.opt_id: po.name for po in profile.optimizations}

                session = optimization_evidence_engine.validate_profile(
                    profile_id=self.pid,
                    optimization_ids=opt_ids,
                    optimization_names=opt_names,
                    duration=8,
                )
                self.complete.emit(session)

        self._val_thread = ValidationThread(profile_id)
        self._val_thread.complete.connect(self._on_validation_complete)
        self._val_thread.start()

    def _on_validation_complete(self, session):
        """Handle validation completion."""
        self.validate_btn.setEnabled(True)
        self.optimize_btn.setEnabled(True)
        self.ab_btn.setEnabled(True)
        self.benchmark_btn.setEnabled(True)
        self.progress_bar.setValue(100)

        if session is None:
            self._log("Validation failed: could not run")
            return

        self._log(f"\nValidation: {len(session.evidence_list)} optimizations tested")
        self._log(f"  Beneficial: {session.beneficial_count}")
        self._log(f"  Neutral: {session.neutral_count}")
        self._log(f"  Harmful: {session.harmful_count}")
        self._log(f"  Inconclusive: {session.inconclusive_count}")
        self._log(f"  Skipped: {session.skipped_count}")

        for ev in session.evidence_list:
            icon = {
                "BENEFICIAL": "+",
                "NEUTRAL": "=",
                "HARMFUL": "-",
                "INCONCLUSIVE": "?",
                "SKIPPED": "~",
            }.get(ev.verdict.value, "?")
            self._log(f"\n  {icon} {ev.optimization_name}: {ev.verdict.value}")
            self._log(f"    {ev.verdict_reason}")
            if ev.fps_delta is not None:
                sign = "+" if ev.fps_delta >= 0 else ""
                self._log(f"    FPS: {sign}{ev.fps_delta:.1f} ({sign}{ev.fps_delta_percent:.1f}%)")
            if ev.was_rolled_back:
                self._log(f"    ROLLED BACK: {ev.rollback_reason}")

    def _restore(self):
        self.restore_btn.setEnabled(False)
        self._log("Restoring...")
        result = optimizer.rollback_last()
        self._log(f"Restore: {result.message}")
        if result.restored_entries:
            self._log(f"  Restored: {', '.join(result.restored_entries)}")
        if result.failed_entries:
            self._log(f"  Failed: {', '.join(result.failed_entries)}")
        self.restore_btn.setEnabled(True)
        # Refresh live state after restore
        self._load_status()

    # ── Gaming Session Controls ──────────────────────────────

    def _start_session(self):
        """Start a gaming session."""
        from app.core.gaming_session import gaming_session_engine, SessionState

        if gaming_session_engine.is_active:
            self._log("Session already active")
            return

        profile_id = self.profile_combo.currentData()
        self.session_start_btn.setEnabled(False)
        self.session_stop_btn.setEnabled(True)
        self.session_status.setText("STARTING")
        self.session_status.setStyleSheet(f"""
            color: {STATUS_WARN}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        self._log(f"Starting gaming session ({profile_id})...")

        class SessionThread(QThread):
            complete = Signal(object)
            def __init__(self, pid):
                super().__init__()
                self.pid = pid
            def run(self):
                from app.core.gaming_session import gaming_session_engine
                session = gaming_session_engine.start_session(self.pid)
                self.complete.emit(session)

        self._session_thread = SessionThread(profile_id)
        self._session_thread.complete.connect(self._on_session_started)
        self._session_thread.start()

        # Start timer
        self._session_start_time = time.time()
        self._session_timer = QTimer(self)
        self._session_timer.timeout.connect(self._update_session_timer)
        self._session_timer.start(1000)

    def _on_session_started(self, session):
        """Handle session start completion."""
        from app.core.gaming_session import SessionState
        self.session_start_btn.setEnabled(session.state != SessionState.MONITORING)
        self.session_stop_btn.setEnabled(session.state == SessionState.MONITORING)

        if session.state == SessionState.FAILED:
            self.session_status.setText("FAILED")
            self.session_status.setStyleSheet(f"""
                color: {STATUS_ERROR}; font-family: {FONT_MONO};
                font-size: {FONT_SIZE_XS}; border: none;
            """)
            for e in session.errors:
                self._log(f"  Error: {e}")
        elif session.state == SessionState.MONITORING:
            self.session_status.setText("ACTIVE")
            self.session_status.setStyleSheet(f"""
                color: {STATUS_OK}; font-family: {FONT_MONO};
                font-size: {FONT_SIZE_XS}; border: none;
            """)
            self._log(f"Session active: {session.session_id}")
            self._log(f"  Target: {session.target_name} PID={session.target_pid}")
            if session.applied_count > 0:
                self._log(f"  Applied: {session.applied_count} optimization(s)")
        else:
            self.session_status.setText(session.state.value)

    def _stop_session(self):
        """Stop the active gaming session."""
        from app.core.gaming_session import gaming_session_engine

        self.session_stop_btn.setEnabled(False)
        self.session_status.setText("STOPPING")
        self.session_status.setStyleSheet(f"""
            color: {STATUS_WARN}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        self._log("Stopping session...")

        class StopThread(QThread):
            complete = Signal(object)
            def run(self):
                from app.core.gaming_session import gaming_session_engine
                session = gaming_session_engine.stop_session()
                self.complete.emit(session)

        self._stop_thread = StopThread()
        self._stop_thread.complete.connect(self._on_session_stopped)
        self._stop_thread.start()

        # Stop timer
        if hasattr(self, '_session_timer') and self._session_timer:
            self._session_timer.stop()

    def _on_session_stopped(self, session):
        """Handle session stop completion."""
        self.session_status.setText("ENDED")
        self.session_status.setStyleSheet(f"""
            color: {STATUS_MUTED}; font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS}; border: none;
        """)
        self.session_start_btn.setEnabled(True)
        self.session_stop_btn.setEnabled(False)
        self.session_restore_btn.setEnabled(session.needs_rollback if hasattr(session, 'needs_rollback') else False)
        self.session_timer.setText(f"{session.duration_seconds:.0f}s")

        self._log(f"Session ended: {session.duration_seconds:.1f}s")
        if session.target_lost:
            self._log("  NOTE: Target was lost during session")
        if session.applied_count > 0:
            self._log(f"  Applied: {session.applied_count}")
            self._log(f"  Restored: {'Yes' if session.snapshot_restored else 'No'}")
        if session.errors:
            for e in session.errors:
                self._log(f"  Error: {e}")

    def _restore_session(self):
        """Restore optimizations from the current session."""
        from app.core.gaming_session import gaming_session_engine

        session = gaming_session_engine.restore_session()
        if session.session_id:
            self._log(f"Session restored: {session.snapshot_restored}")
            self.session_restore_btn.setEnabled(False)
        else:
            self._log("No session to restore")

    def _update_session_timer(self):
        """Update the session timer display."""
        if hasattr(self, '_session_start_time') and self._session_start_time:
            elapsed = time.time() - self._session_start_time
            mins = int(elapsed) // 60
            secs = int(elapsed) % 60
            self.session_timer.setText(f"{mins:02d}:{secs:02d}")

    def _export_report(self):
        """Export a performance report to JSON."""
        try:
            from app.core.performance_report import performance_report_generator
            report = performance_report_generator.generate()
            path = performance_report_generator.export_json(report)
            self._log(f"Report exported: {path}")
        except Exception as e:
            self._log(f"Export failed: {e}")

    def _load_windows_status(self):
        """Load Windows gaming diagnostics into the compact section."""
        try:
            from app.system.windows_gaming import windows_gaming_analyzer
            from app.core.emulator_controller import emulator_controller

            target = emulator_controller.detect_target()
            t_name = target.name if target else ""
            t_pid = target.pid if target else 0

            report = windows_gaming_analyzer.analyze(t_name, t_pid)

            # Update status label
            enabled = sum(1 for i in report.items if i.status == "ENABLED")
            disabled = sum(1 for i in report.items if i.status == "DISABLED")
            self.win_status_label.setText(
                f"{enabled} enabled \u2022 {disabled} disabled"
            )

            # Clear existing items
            while self.win_items_layout.count() > 0:
                item = self.win_items_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            # Add diagnostic rows
            for diag_item in report.items:
                row = OptRow(diag_item.name, diag_item.value)
                status_map = {
                    "ENABLED": ("ENABLED ✓", STATUS_OK),
                    "DISABLED": ("DISABLED ✓", STATUS_OK),
                    "AVAILABLE": ("AVAILABLE", STATUS_MUTED),
                    "NOT AVAILABLE": ("NOT AVAILABLE", STATUS_MUTED),
                    "UNKNOWN": ("UNKNOWN", STATUS_MUTED),
                    "REQUIRES ADMIN": ("REQUIRES ADMIN", STATUS_WARN),
                }
                label, color = status_map.get(diag_item.status, (diag_item.status, STATUS_MUTED))
                row.set_status(label, color)
                self.win_items_layout.addWidget(row)

        except Exception as e:
            logger.debug(f"Windows status load: {e}")

    def _start_windows_optimize(self):
        """Apply Windows gaming optimizations (uses gaming profile)."""
        self.win_apply_btn.setEnabled(False)
        self._log("Applying Windows gaming optimizations...")

        # Use the existing optimizer with gaming profile — includes game_bar and recording
        self._thread = ApplyThread("gaming")
        self._thread.progress.connect(self._on_progress)
        self._thread.complete.connect(self._on_windows_complete)
        self._thread.start()

    def _on_windows_complete(self, report):
        """Handle Windows optimization completion."""
        self.win_apply_btn.setEnabled(True)
        self._on_complete(report)
        # Refresh Windows diagnostics
        self._load_windows_status()

    def _load_resource_status(self):
        """Load resource analysis into the compact section."""
        try:
            from app.core.resource_analyzer import resource_analyzer
            from app.core.emulator_controller import emulator_controller
            from app.core.telemetry import telemetry_engine

            target = emulator_controller.detect_target()
            t_pid = target.pid if target else 0
            t_name = target.name if target else ""

            frame = telemetry_engine.current

            # GPU info
            gpu_info = {}
            try:
                from app.system.gpu import gpu_monitor
                gpus = gpu_monitor.detect()
                if gpus and gpus[0].vendor == "NVIDIA":
                    gpu = gpu_monitor.update_nvidia(gpus[0])
                    gpu_info = {
                        "vram_total_mb": gpu.vram_total_mb,
                        "vram_used_mb": gpu.vram_used_mb,
                        "utilization": gpu.utilization_gpu,
                    }
            except Exception:
                pass

            status = resource_analyzer.analyze(
                emulator_pid=t_pid,
                emulator_name=t_name,
                telemetry_frame=frame,
                gpu_info=gpu_info,
            )

            # Update RAM
            if status.ram:
                self.res_ram_val.setText(
                    f"{status.ram.used_gb:.1f}/{status.ram.total_gb:.1f}GB"
                )
                pressure_color = {
                    "OPTIMAL": STATUS_OK,
                    "MODERATE": STATUS_WARN,
                    "HIGH": STATUS_ERROR,
                    "CRITICAL": STATUS_ERROR,
                }.get(status.ram.pressure_level, TEXT_TERTIARY)
                self.res_ram_val.setStyleSheet(f"""
                    color: {pressure_color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD}; border: none;
                """)

            # Update emulator
            if status.emulator:
                self.res_emu_cpu_val.setText(f"{status.emulator.cpu_percent:.0f}%")
                self.res_emu_ram_val.setText(f"{status.emulator.rss_mb:.0f}MB")
            else:
                self.res_emu_cpu_val.setText("N/A")
                self.res_emu_ram_val.setText("N/A")

            # Update GPU
            if gpu_info.get("vram_total_mb", 0) > 0:
                vram_pct = (gpu_info["vram_used_mb"] / gpu_info["vram_total_mb"]) * 100
                self.res_gpu_val.setText(f"{gpu_info['utilization']:.0f}%")
            else:
                self.res_gpu_val.setText("N/A")

            # Update bottleneck
            if status.bottleneck:
                b = status.bottleneck
                bn_colors = {
                    "CPU_BOUND": STATUS_WARN,
                    "GPU_BOUND": STATUS_ERROR,
                    "MEMORY_PRESSURE": STATUS_ERROR,
                    "FRAME_TIME_LIMITED": STATUS_WARN,
                    "NO_CLEAR_BOTTLENECK": STATUS_OK,
                    "INCONCLUSIVE": STATUS_MUTED,
                }
                color = bn_colors.get(b.classification, TEXT_TERTIARY)
                self.res_bottleneck_label.setText(f"{b.classification}")
                self.res_bottleneck_label.setStyleSheet(f"""
                    color: {color}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
                    font-weight: {WEIGHT_BOLD}; border: none;
                """)

            # Update top recommendation
            if status.recommendations:
                top = status.recommendations[0]
                self.res_rec_label.setText(f"[{top.priority}] {top.title}: {top.reason}")
            else:
                self.res_rec_label.setText("System is well-optimized")

        except Exception as e:
            logger.debug(f"Resource status load: {e}")

    def _load_background_status(self):
        """Load background load analysis into the compact section."""
        try:
            from app.system.background_analyzer import background_analyzer, CompetitionLevel
            from app.core.emulator_controller import emulator_controller

            target = emulator_controller.detect_target()
            t_pid = target.pid if target else 0
            t_name = target.name if target else ""

            result = background_analyzer.analyze(
                emulator_pid=t_pid,
                emulator_name=t_name,
            )

            # Update overall impact
            impact_colors = {
                CompetitionLevel.NONE: STATUS_OK,
                CompetitionLevel.LOW: STATUS_OK,
                CompetitionLevel.MODERATE: STATUS_WARN,
                CompetitionLevel.HIGH: STATUS_ERROR,
                CompetitionLevel.SEVERE: STATUS_ERROR,
            }
            color = impact_colors.get(result.overall_impact_level, TEXT_TERTIARY)
            self.bg_impact_label.setText(result.overall_impact_level.value)
            self.bg_impact_label.setStyleSheet(f"""
                color: {color}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
                font-weight: {WEIGHT_BOLD}; border: none;
            """)

            # Update CPU competition
            if result.cpu_competition:
                c = result.cpu_competition
                c_color = impact_colors.get(c.level, TEXT_TERTIARY)
                self.bg_cpu_val.setText(f"{c.total_competition_cpu:.1f}%")
                self.bg_cpu_val.setStyleSheet(f"""
                    color: {c_color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD}; border: none;
                """)
            else:
                self.bg_cpu_val.setText("N/A")

            # Update RAM competition
            if result.ram_competition:
                c = result.ram_competition
                c_color = impact_colors.get(c.level, TEXT_TERTIARY)
                self.bg_ram_val.setText(f"{c.total_competition_ram_mb / 1024:.1f}GB")
                self.bg_ram_val.setStyleSheet(f"""
                    color: {c_color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD}; border: none;
                """)
            else:
                self.bg_ram_val.setText("N/A")

            # Update Disk competition
            if result.disk_competition:
                c = result.disk_competition
                c_color = impact_colors.get(c.level, TEXT_TERTIARY)
                self.bg_disk_val.setText(f"{c.total_competition_ram_mb:.0f}MB")
                self.bg_disk_val.setStyleSheet(f"""
                    color: {c_color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD}; border: none;
                """)
            else:
                self.bg_disk_val.setText("N/A")

            # Update recommendation
            if result.safe_candidates:
                names = [p.name for p in result.safe_candidates[:3]]
                self.bg_rec_label.setText(
                    f"{len(result.safe_candidates)} process(es) safe to close: {', '.join(names)}"
                )
            else:
                self.bg_rec_label.setText(result.overall_description)

        except Exception as e:
            logger.debug(f"Background status load: {e}")

    def _load_memory_status(self):
        """Load memory optimization analysis into the compact section."""
        try:
            from app.system.memory_optimizer import memory_optimizer, ProcessCategory
            from app.core.emulator_controller import emulator_controller

            target = emulator_controller.detect_target()
            t_pid = target.pid if target else 0
            t_name = target.name if target else ""

            report = memory_optimizer.analyze(
                emulator_pid=t_pid,
                emulator_name=t_name,
            )

            # Pressure level
            pressure_colors = {
                "NORMAL": STATUS_OK,
                "MODERATE": STATUS_WARN,
                "HIGH": STATUS_ERROR,
                "CRITICAL": STATUS_ERROR,
                "UNKNOWN": STATUS_MUTED,
            }
            if report.diagnostics:
                level = report.diagnostics.pressure_level
                color = pressure_colors.get(level, TEXT_TERTIARY)
                self.mem_pressure_label.setText(level)
                self.mem_pressure_label.setStyleSheet(f"""
                    color: {color}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
                    font-weight: {WEIGHT_BOLD}; border: none;
                """)

                # Available RAM
                avail_color = STATUS_OK if level in ("NORMAL", "MODERATE") else STATUS_ERROR
                self.mem_avail_val.setText(f"{report.diagnostics.available_gb:.1f}GB")
                self.mem_avail_val.setStyleSheet(f"""
                    color: {avail_color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD}; border: none;
                """)

                # Used RAM
                self.mem_used_val.setText(
                    f"{report.diagnostics.used_gb:.1f}/{report.diagnostics.total_gb:.1f}GB"
                )
            else:
                self.mem_pressure_label.setText("N/A")
                self.mem_avail_val.setText("N/A")
                self.mem_used_val.setText("N/A")

            # Emulator RAM
            if report.emulator:
                emu_color = STATUS_WARN if report.emulator.is_high_usage else STATUS_OK
                self.mem_emu_val.setText(f"{report.emulator.rss_mb:.0f}MB")
                self.mem_emu_val.setStyleSheet(f"""
                    color: {emu_color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD}; border: none;
                """)
            else:
                self.mem_emu_val.setText("N/A")

            # Top user
            safe = memory_optimizer.get_safe_closeable_processes(emulator_pid=t_pid)
            if safe:
                self.mem_top_val.setText(f"{safe[0]['name'][:15]} {safe[0]['rss_mb']:.0f}MB")
            else:
                self.mem_top_val.setText("None safe to close")

            # Recommendation
            if report.recommendations:
                top = report.recommendations[0]
                self.mem_rec_label.setText(f"[{top['priority']}] {top['title']}")
            else:
                self.mem_rec_label.setText("Memory usage is healthy")

        except Exception as e:
            logger.debug(f"Memory status load: {e}")

    def _load_startup_status(self):
        """Load startup analysis into the compact section."""
        try:
            from app.system.startup_analyzer import startup_analyzer

            analysis = startup_analyzer.analyze()

            # Total entries
            self.startup_total_val.setText(str(analysis.total_entries))

            # Optional entries
            opt_count = analysis.optional_entries
            opt_color = STATUS_WARN if opt_count > 3 else STATUS_OK
            self.startup_optional_val.setText(str(opt_count))
            self.startup_optional_val.setStyleSheet(f"""
                color: {opt_color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
                font-weight: {WEIGHT_BOLD}; border: none;
            """)

            # Optional RAM
            optional_ram = startup_analyzer.get_ram_usage_of_optional()
            if optional_ram > 100:
                self.startup_ram_val.setText(f"{optional_ram:.0f}MB")
                self.startup_ram_val.setStyleSheet(f"""
                    color: {STATUS_WARN}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD}; border: none;
                """)
            else:
                self.startup_ram_val.setText(f"{optional_ram:.0f}MB")

            # Count label
            self.startup_count_label.setText(f"{analysis.enabled_entries}/{analysis.total_entries} enabled")

            # Recommendation
            if analysis.optional_names:
                names = ", ".join(analysis.optional_names[:3])
                self.startup_rec_label.setText(
                    f"{len(analysis.optional_names)} optional: {names}"
                )
            else:
                self.startup_rec_label.setText("No optional startup entries detected")

        except Exception as e:
            logger.debug(f"Startup status load: {e}")

    def _load_telemetry_status(self):
        """Load telemetry status into the compact section."""
        try:
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current

            if frame is None or frame.timestamp == 0:
                self.telemetry_status_label.setText("--")
                return

            self.telemetry_status_label.setText("LIVE")

            # FPS from active FPS provider
            fps_text = "N/A"
            try:
                from app.performance.fps_provider import fps_registry
                if fps_registry.active and hasattr(fps_registry.active, 'get_metrics'):
                    metrics = fps_registry.active.get_metrics()
                    if metrics and metrics.available and metrics.sample_count > 0:
                        fps_val = metrics.median_fps if metrics.median_fps > 0 else metrics.avg_fps
                        fps_text = f"{fps_val:.0f}"
            except Exception:
                pass
            self.telem_fps_val.setText(fps_text)

            # CPU
            self.telem_cpu_val.setText(f"{frame.cpu_utilization:.0f}%")

            # GPU
            if frame.gpu_utilization > 0:
                self.telem_gpu_val.setText(f"{frame.gpu_utilization:.0f}%")
            else:
                self.telem_gpu_val.setText("N/A")

            # RAM
            self.telem_ram_val.setText(f"{frame.ram_percent:.0f}%")

            # Bottleneck hint from thermal status
            if frame.thermal_status == "THROTTLING":
                self.telem_bottleneck_label.setText("Thermal throttling detected")
                self.telem_bottleneck_label.setStyleSheet(f"""
                    color: {STATUS_WARN}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
                    border: none;
                """)
            else:
                self.telem_bottleneck_label.setText("")

        except Exception as e:
            logger.debug(f"Telemetry status load: {e}")

    def _load_recommendations(self):
        """Load recommendation status into the compact section."""
        try:
            from app.core.recommendation_engine import recommendation_engine
            from app.core.optimizer import optimizer
            from app.performance.telemetry_models import BottleneckType

            # Get current optimization states
            opt_status = optimizer.get_current_status()
            states = {}
            for opt in opt_status.get("optimizations", []):
                states[opt["id"]] = opt.get("status", "UNKNOWN")

            # Get target info
            target_name = opt_status.get("target_name", "")
            target_pid = opt_status.get("target_pid", 0)

            # Try quick telemetry from the existing collector
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current

            # Build minimal samples for recommendation engine
            samples = []
            if frame and frame.timestamp > 0:
                from app.performance.telemetry_models import TelemetrySample
                sample = TelemetrySample(
                    timestamp=frame.timestamp,
                    emulator_pid=target_pid,
                    emulator_name=target_name,
                    cpu_total_percent=frame.cpu_utilization,
                    gpu_utilization_percent=frame.gpu_utilization,
                    system_ram_used_mb=frame.ram_used_mb,
                    system_ram_total_mb=frame.ram_total_mb,
                    system_ram_available_mb=frame.ram_total_mb - frame.ram_used_mb if frame.ram_total_mb else None,
                )
                samples.append(sample)

            # Determine bottleneck from thermal status
            bottleneck = BottleneckType.INSUFFICIENT_DATA
            bn_confidence = 0
            if frame:
                if frame.thermal_status == "THROTTLING":
                    bottleneck = BottleneckType.THERMAL_LIMITED
                    bn_confidence = 70
                elif frame.cpu_utilization > 85:
                    bottleneck = BottleneckType.CPU_BOUND
                    bn_confidence = 60
                elif frame.gpu_utilization > 90:
                    bottleneck = BottleneckType.GPU_BOUND
                    bn_confidence = 60
                elif frame.ram_percent > 85:
                    bottleneck = BottleneckType.MEMORY_BOUND
                    bn_confidence = 60
                else:
                    bottleneck = BottleneckType.NO_CLEAR_BOTTLENECK
                    bn_confidence = 40

            session = recommendation_engine.analyze(
                samples=samples,
                bottleneck_type=bottleneck,
                bottleneck_confidence=bn_confidence,
                optimization_states=states,
                target_name=target_name,
                target_pid=target_pid,
            )

            # Update labels
            bn_str = session.bottleneck.replace("_", " ").title()
            self.rec_bottleneck_label.setText(
                f"Bottleneck: {bn_str} ({session.bottleneck_confidence}%)"
            )
            self.rec_quality_label.setText(session.telemetry_quality.value)

            top = session.get_top_recommendations(3)
            if top:
                first = top[0]
                self.rec_top_label.setText(
                    f"Top: {first.optimization_name} — {first.priority.value}"
                )
                evidence_str = first.reason[:100]
                self.rec_detail_label.setText(f"{evidence_str}")
            else:
                self.rec_top_label.setText("No actionable recommendations")
                self.rec_detail_label.setText("")

        except Exception as e:
            logger.debug(f"Recommendations load: {e}")

    def _load_adaptive_status(self):
        """Load adaptive optimization status into the compact section."""
        try:
            from app.core.adaptive_optimizer import adaptive_optimizer
            from app.core.optimizer import optimizer
            from app.core.telemetry import telemetry_engine
            from app.performance.telemetry_models import TelemetrySample, BottleneckType

            # Get optimization states
            opt_status = optimizer.get_current_status()
            states = {o["id"]: o.get("status", "UNKNOWN") for o in opt_status.get("optimizations", [])}
            target_name = opt_status.get("target_name", "")
            target_pid = opt_status.get("target_pid", 0)

            # Get telemetry samples
            frame = telemetry_engine.current
            samples = []
            if frame and frame.timestamp > 0:
                sample = TelemetrySample(
                    timestamp=frame.timestamp,
                    emulator_pid=target_pid,
                    emulator_name=target_name,
                    cpu_total_percent=frame.cpu_utilization,
                    gpu_utilization_percent=frame.gpu_utilization,
                    system_ram_used_mb=frame.ram_used_mb,
                    system_ram_total_mb=frame.ram_total_mb,
                    system_ram_available_mb=frame.ram_total_mb - frame.ram_used_mb if frame.ram_total_mb else None,
                )
                samples.append(sample)

            state, confidence, evidence = adaptive_optimizer.classify_state(samples)
            state_str = state.value.replace("_", " ").title()

            self.adaptive_state_label.setText(f"{state_str} ({confidence}%)")

            plan = adaptive_optimizer.generate_plan(
                samples=samples, state=state, state_confidence=confidence,
                state_evidence=evidence, optimization_states=states,
                target_name=target_name, target_pid=target_pid,
            )

            self.adaptive_profile_label.setText(f"Profile: {plan.recommended_profile.upper()}")

            applicable = [a for a in plan.actions if a.status.value in (
                "APPLIED", "ALREADY_OPTIMAL", "REQUIRES_ADMIN", "RECOMMENDATION_ONLY",
            )]
            if applicable:
                first = applicable[0]
                self.adaptive_action_label.setText(
                    f"Top: {first.optimization_name} — {first.status.value.replace('_', ' ')}"
                )
            else:
                if state.value == "OPTIMAL":
                    self.adaptive_action_label.setText("System is optimal — no actions needed")
                elif state.value == "INSUFFICIENT_DATA":
                    self.adaptive_action_label.setText("Collect more telemetry")
                else:
                    self.adaptive_action_label.setText("")

        except Exception as e:
            logger.debug(f"Adaptive status load: {e}")

    def _load_input_status(self):
        """Load input & gameplay status into the compact section."""
        try:
            from app.input.input_diagnostics import run_input_diagnostics
            from app.input.gameplay_diagnostics import run_gameplay_diagnostics
            from app.core.telemetry import telemetry_engine
            from app.performance.telemetry_models import TelemetrySample
            from app.core.optimizer import optimizer

            opt_status = optimizer.get_current_status()
            target_name = opt_status.get("target_name", "")
            target_pid = opt_status.get("target_pid", 0)

            frame = telemetry_engine.current
            samples = []
            if frame and frame.timestamp > 0:
                sample = TelemetrySample(
                    timestamp=frame.timestamp,
                    emulator_pid=target_pid,
                    emulator_name=target_name,
                    cpu_total_percent=frame.cpu_utilization,
                    gpu_utilization_percent=frame.gpu_utilization,
                    system_ram_used_mb=frame.ram_used_mb,
                    system_ram_total_mb=frame.ram_total_mb,
                    system_ram_available_mb=frame.ram_total_mb - frame.ram_used_mb if frame.ram_total_mb else None,
                )
                samples.append(sample)

            input_session = run_input_diagnostics(
                target_name=target_name, target_pid=target_pid,
            )

            gameplay = run_gameplay_diagnostics(
                samples=samples, input_session=input_session,
                target_name=target_name, target_pid=target_pid,
            )

            # Update labels
            cond_str = gameplay.condition.value.replace("_", " ").title()
            self.input_condition_label.setText(f"Condition: {cond_str}")

            cs = gameplay.consistency_score
            if cs.overall_score > 0:
                self.input_score_label.setText(f"{cs.overall_score}/100 ({cs.level.value})")
            else:
                self.input_score_label.setText("N/A")

            # Detail: pointer + polling
            pc = input_session.pointer_config
            epp = "ON" if pc.enhance_pointer_precision else "OFF"
            detail = f"Pointer Accel: {epp}"
            if input_session.polling and input_session.polling.observed_rate_hz > 0:
                detail += f"  |  Rate: {input_session.polling.observed_rate_hz:.0f}Hz ({input_session.polling.consistency.value})")
            self.input_detail_label.setText(detail)

            # Top recommendation
            if gameplay.recommendations:
                top = gameplay.recommendations[0]
                self.input_rec_label.setText(f"{top.category}: {top.reason[:100]}")
            else:
                self.input_rec_label.setText("")

        except Exception as e:
            logger.debug(f"Input status load: {e}")

    def _log(self, msg):
        self.log_text.append(msg)
