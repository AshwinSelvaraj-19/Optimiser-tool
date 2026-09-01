"""
Heaven Society — HOME Page

Compact real-time overview:
- Target/emulator detection status
- Real FPS from PresentMon (or N/A)
- System metrics (CPU/GPU/RAM/Temp)
- Performance status
- Quick action buttons
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QGridLayout, QSpacerItem, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer

from app.ui.theme import (
    BG_PANEL, BG_PRIMARY, BG_INPUT, BORDER_LIGHT, BORDER_MEDIUM,
    ACCENT_PRIMARY, ACCENT_LIGHT, ACCENT_SUBTLE, ACCENT_BG,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY, TEXT_INVERSE,
    STATUS_OK, STATUS_WARN, STATUS_ERROR, STATUS_MUTED,
    FONT_FAMILY, FONT_MONO,
    FONT_SIZE_XL, FONT_SIZE_LG, FONT_SIZE_MD, FONT_SIZE_SM, FONT_SIZE_XS,
    WEIGHT_BOLD, WEIGHT_SEMIBOLD, WEIGHT_MEDIUM, WEIGHT_REGULAR,
    RADIUS_MD, RADIUS_LG, RADIUS_XL,
    SPACING_SM, SPACING_MD, SPACING_LG, SPACING_XL,
    metric_color, temp_color, card_style, button_primary_style,
    button_secondary_style,
)
from app.utils.logger import get_logger
from app.ui.home_page_worker import HomePageWorkerThread, HomePageResult

logger = get_logger("ui.home_page")


class MetricBlock(QFrame):
    """Compact single-value metric display."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.NoFrame)
        self.setStyleSheet(f"""
            QFrame {{
                {card_style()}
                padding: 2px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_SEMIBOLD};
            letter-spacing: 1px;
            border: none;
        """)

        self.value_label = QLabel("--")
        self.value_label.setStyleSheet(f"""
            color: {TEXT_PRIMARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_LG};
            font-weight: {WEIGHT_BOLD};
            border: none;
        """)
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.unit_label = QLabel("")
        self.unit_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)

        self._last_value = "--"
        self._last_color = TEXT_PRIMARY
        self._last_unit = ""

        layout.addWidget(self.title_label)
        h = QHBoxLayout()
        h.setSpacing(3)
        h.addWidget(self.value_label)
        h.addWidget(self.unit_label)
        h.addStretch()
        layout.addLayout(h)

    def set_value(self, value: str, color: str = TEXT_PRIMARY, unit: str = ""):
        if value == self._last_value and color == self._last_color and unit == self._last_unit:
            return  # no change, skip expensive stylesheet rebuild
        self._last_value = value
        self._last_color = color
        self._last_unit = unit
        self.value_label.setText(value)
        self.value_label.setStyleSheet(f"""
            color: {color};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_LG};
            font-weight: {WEIGHT_BOLD};
            border: none;
        """)
        self.unit_label.setText(unit)


class TargetPanel(QFrame):
    """Compact target/emulator detection panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.NoFrame)
        self.setMinimumHeight(80)
        self.setStyleSheet(f"""
            QFrame {{
                {card_style()}
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(16)

        # Status dot + text
        left = QVBoxLayout()
        left.setSpacing(2)

        self.status_label = QLabel("○ NO EMULATOR DETECTED")
        self.status_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_SEMIBOLD};
            border: none;
        """)
        left.addWidget(self.status_label)

        self.process_label = QLabel("")
        self.process_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        left.addWidget(self.process_label)

        layout.addLayout(left, 1)

        # GPU info
        right = QVBoxLayout()
        right.setSpacing(2)

        self.gpu_label = QLabel("GPU")
        self.gpu_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_SEMIBOLD};
            letter-spacing: 1px;
            border: none;
        """)
        right.addWidget(self.gpu_label)

        self.gpu_value = QLabel("--")
        self.gpu_value.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_SM};
            border: none;
        """)
        right.addWidget(self.gpu_value)

        layout.addLayout(right)

    def set_detected(self, name: str, process: str, pid: int, gpu: str):
        self.status_label.setText(f"● {name}")
        self.status_label.setStyleSheet(f"""
            color: {STATUS_OK};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_SEMIBOLD};
            border: none;
        """)
        self.process_label.setText(f"{process}  PID {pid}")
        self.gpu_value.setText(gpu)

    def set_not_detected(self):
        self.status_label.setText("○ NO EMULATOR DETECTED")
        self.status_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_SEMIBOLD};
            border: none;
        """)
        self.process_label.setText("")
        self.gpu_value.setText("--")


class HomePage(QWidget):
    """Home page — compact Heaven Society overview."""
    navigate_to = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker_thread: HomePageWorkerThread | None = None
        self._last_result: HomePageResult | None = None
        self._gaming_mode = False
        self._hidden_widgets = []  # widgets hidden in gaming mode
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start(2000)  # 2s between refresh requests

    def set_gaming_mode(self, enabled: bool):
        """Toggle compact gaming mode: hide non-essential labels."""
        self._gaming_mode = enabled
        for w in self._hidden_widgets:
            try:
                w.setVisible(not enabled)
            except Exception:
                pass
        # Compact the metrics grid in gaming mode
        if hasattr(self, 'target_panel') and self.target_panel:
            self.target_panel.setMinimumHeight(50 if enabled else 80)

    # ── Background worker refresh ─────────────────────────────

    def refresh(self):
        """Non-blocking refresh: dispatch heavy work to background."""
        self._update_metrics()  # fast — reads cached telemetry
        self._start_worker()

    def _on_timer(self):
        """Periodic refresh while page is visible."""
        self._update_metrics()  # fast
        self._start_worker()

    def _start_worker(self):
        if self._worker_thread and self._worker_thread.isRunning():
            return
        self._worker_thread = HomePageWorkerThread(self)
        self._worker_thread.finished.connect(self._on_worker_result)
        self._worker_thread.error.connect(self._on_worker_error)
        self._worker_thread.start()

    def _on_worker_result(self, result: HomePageResult):
        self._last_result = result
        try:
            self._apply_target(result)
            self._apply_status(result)
            self._apply_gaming_analysis(result)
        except Exception as e:
            logger.debug(f"HomePage apply: {e}")
        self._worker_thread = None

    def _on_worker_error(self, msg: str):
        logger.debug(f"HomePage worker error: {msg}")
        self._worker_thread = None

    def _update(self):
        """Legacy entry point — non-blocking."""
        self.refresh()

    # ── Fast methods (GUI thread, read cached telemetry) ──────

    def _update_metrics(self):
        """Update metric blocks from cached telemetry — FAST."""
        try:
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current

            if frame.cpu_utilization > 0:
                self.cpu_block.set_value(
                    f"{frame.cpu_utilization:.0f}",
                    color=metric_color(frame.cpu_utilization),
                    unit="%"
                )
            else:
                self.cpu_block.set_value("--", color=TEXT_TERTIARY)

            if frame.gpu_utilization > 0:
                self.gpu_block.set_value(
                    f"{frame.gpu_utilization:.0f}",
                    color=metric_color(frame.gpu_utilization),
                    unit="%"
                )
            else:
                self.gpu_block.set_value("--", color=TEXT_TERTIARY)

            if frame.ram_percent > 0:
                self.ram_block.set_value(
                    f"{frame.ram_percent:.0f}",
                    color=metric_color(frame.ram_percent),
                    unit="%"
                )
            else:
                self.ram_block.set_value("--", color=TEXT_TERTIARY)

            if frame.gpu_temp is not None and frame.gpu_temp > 0:
                self.temp_block.set_value(
                    f"{frame.gpu_temp:.0f}",
                    color=temp_color(frame.gpu_temp),
                    unit="\u00b0C"
                )
            else:
                self.temp_block.set_value("N/A", color=TEXT_TERTIARY)

            self._update_fps_from_telemetry()
        except Exception as e:
            logger.debug(f"Metrics update: {e}")

    def _update_fps_from_telemetry(self):
        """Update FPS from cached FPS provider — FAST."""
        try:
            from app.performance.fps_provider import fps_registry
            if fps_registry.active and hasattr(fps_registry.active, 'get_metrics'):
                metrics = fps_registry.active.get_metrics()
                if metrics and metrics.available and metrics.sample_count > 0:
                    fps_val = metrics.median_fps if metrics.median_fps > 0 else metrics.avg_fps
                    self.fps_block.set_value(f"{fps_val:.0f}", color=STATUS_OK)
                    if metrics.one_percent_low > 0:
                        self.one_low_block.set_value(f"{metrics.one_percent_low:.0f}", color=STATUS_WARN)
                    if metrics.average_frame_time > 0:
                        self.frame_time_block.set_value(f"{metrics.average_frame_time:.1f}", color=STATUS_OK, unit="ms")
                    return
            # No FPS data
            self.fps_block.set_value("--", color=STATUS_MUTED)
            self.one_low_block.set_value("--", color=STATUS_MUTED)
            self.frame_time_block.set_value("--", color=STATUS_MUTED)
            self.stability_block.set_value("--", color=STATUS_MUTED)
        except Exception:
            self.fps_block.set_value("N/A", color=TEXT_TERTIARY)
            self.one_low_block.set_value("N/A", color=TEXT_TERTIARY)
            self.frame_time_block.set_value("N/A", color=TEXT_TERTIARY)
            self.stability_block.set_value("--", color=TEXT_TERTIARY)

    # ── Apply methods (from worker result) ────────────────────

    def _apply_target(self, result: HomePageResult):
        if result.target_pid:
            self.target_panel.set_detected(
                name=result.target_emulator,
                process=result.target_process,
                pid=result.target_pid,
                gpu=result.target_gpu,
            )
        else:
            self.target_panel.set_not_detected()

    def _apply_status(self, result: HomePageResult):
        try:
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current

            if frame.cpu_utilization <= 0 and frame.gpu_utilization <= 0:
                self.perf_status.setText("IDLE")
                self.perf_status.setStyleSheet(f"""
                    color: {STATUS_MUTED}; font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;
                """)
            elif frame.gpu_utilization > 90:
                self.perf_status.setText("GPU LIMITED")
                self.perf_status.setStyleSheet(f"""
                    color: {STATUS_ERROR}; font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;
                """)
            elif frame.cpu_utilization > 90:
                self.perf_status.setText("CPU LIMITED")
                self.perf_status.setStyleSheet(f"""
                    color: {STATUS_WARN}; font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;
                """)
            elif frame.gpu_temp and frame.gpu_temp > 85:
                self.perf_status.setText("THERMAL WARNING")
                self.perf_status.setStyleSheet(f"""
                    color: {STATUS_ERROR}; font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;
                """)
            else:
                self.perf_status.setText("STABLE")
                self.perf_status.setStyleSheet(f"""
                    color: {STATUS_OK}; font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;
                """)

            # PresentMon status
            if result.pm_available:
                self.pm_status.setText("PresentMon \u25cf READY")
                self.pm_status.setStyleSheet(f"""
                    color: {STATUS_OK}; font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_XS}; border: none;
                """)
            else:
                self.pm_status.setText("PresentMon \u25cf UNAVAILABLE")
                self.pm_status.setStyleSheet(f"""
                    color: {STATUS_ERROR}; font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_XS}; border: none;
                """)

            # Hardware class
            if result.hw_tier:
                self.hw_class_label.setText(result.hw_tier)
            else:
                self.hw_class_label.setText("")

        except Exception as e:
            logger.debug(f"Status apply: {e}")

    def _apply_gaming_analysis(self, result: HomePageResult):
        try:
            decision = result.decision
            if decision is None:
                return

            bn_name = decision.bottleneck.value
            if bn_name == "UNKNOWN":
                bn_name = "ANALYZING"
            self.ga_bottleneck.setText(f"BOTTLENECK: {bn_name}")
            bn_color = STATUS_MUTED
            if decision.bottleneck_confidence > 0.7:
                bn_color = STATUS_ERROR
            elif decision.bottleneck_confidence > 0.4:
                bn_color = STATUS_WARN
            self.ga_bottleneck.setStyleSheet(f"""
                color: {bn_color};
                font-family: {FONT_MONO}; font-size: {FONT_SIZE_XS};
                border: none;
            """)

            conf_pct = f"{decision.bottleneck_confidence:.0%}"
            self.ga_confidence.setText(f"CONFIDENCE: {conf_pct}")

            applicable = sum(1 for o in decision.recommended_optimizations if o.status == "APPLICABLE")
            total = len(decision.recommended_optimizations)
            self.ga_actions.setText(f"ACTIONS: {applicable}/{total}")

        except Exception as e:
            logger.debug(f"Gaming analysis apply: {e}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # ── Section: TARGET ──────────────────────────────────
        section_target = QLabel("TARGET")
        section_target.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 2px;
            border: none;
        """)
        layout.addWidget(section_target)

        self.target_panel = TargetPanel()
        layout.addWidget(self.target_panel)

        # ── Section: PERFORMANCE ─────────────────────────────
        section_perf = QLabel("PERFORMANCE")
        section_perf.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 2px;
            border: none;
        """)
        layout.addWidget(section_perf)

        # FPS row
        fps_grid = QHBoxLayout()
        fps_grid.setSpacing(8)

        self.fps_block = MetricBlock("FPS")
        self.one_low_block = MetricBlock("1% LOW")
        self.frame_time_block = MetricBlock("FRAME TIME")
        self.stability_block = MetricBlock("STABILITY")
        self._hidden_widgets.append(self.stability_block)

        fps_grid.addWidget(self.fps_block)
        fps_grid.addWidget(self.one_low_block)
        fps_grid.addWidget(self.frame_time_block)
        fps_grid.addWidget(self.stability_block)

        layout.addLayout(fps_grid)

        # ── Section: SYSTEM ──────────────────────────────────
        section_sys = QLabel("SYSTEM")
        section_sys.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 2px;
            border: none;
        """)
        layout.addWidget(section_sys)

        sys_grid = QHBoxLayout()
        sys_grid.setSpacing(8)

        self.cpu_block = MetricBlock("CPU")
        self.gpu_block = MetricBlock("GPU")
        self.ram_block = MetricBlock("RAM")
        self.temp_block = MetricBlock("GPU TEMP")

        sys_grid.addWidget(self.cpu_block)
        sys_grid.addWidget(self.gpu_block)
        sys_grid.addWidget(self.ram_block)
        sys_grid.addWidget(self.temp_block)

        layout.addLayout(sys_grid)

        # ── Section: PERFORMANCE STATUS ──────────────────────
        status_frame = QFrame()
        status_frame.setStyleSheet(f"""
            QFrame {{
                {card_style()}
            }}
        """)
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(14, 8, 14, 8)
        status_layout.setSpacing(8)

        perf_title = QLabel("STATUS")
        perf_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_SEMIBOLD};
            letter-spacing: 1px;
            border: none;
        """)
        status_layout.addWidget(perf_title)

        self.perf_status = QLabel("ANALYZING")
        self.perf_status.setStyleSheet(f"""
            color: {STATUS_MUTED};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD};
            border: none;
        """)
        status_layout.addWidget(self.perf_status)

        status_layout.addStretch()

        # PresentMon status
        self.pm_status = QLabel("PresentMon ● --")
        self.pm_status.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        status_layout.addWidget(self.pm_status)

        # Hardware class
        self.hw_class_label = QLabel("")
        self.hw_class_label.setStyleSheet(f"""
            color: {ACCENT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            border: none;
        """)
        status_layout.addWidget(self.hw_class_label)

        layout.addWidget(status_frame)

        # ── Section: GAMING ANALYSIS ─────────────────────────
        section_ga = QLabel("GAMING ANALYSIS")
        section_ga.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 2px;
            border: none;
        """)
        layout.addWidget(section_ga)
        self._hidden_widgets.append(section_ga)

        self.ga_frame = QFrame()
        self.ga_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        ga_layout = QHBoxLayout(self.ga_frame)
        ga_layout.setContentsMargins(12, 6, 12, 6)
        ga_layout.setSpacing(16)

        self.ga_bottleneck = QLabel("BOTTLENECK: --")
        self.ga_bottleneck.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        ga_layout.addWidget(self.ga_bottleneck)

        self.ga_confidence = QLabel("CONFIDENCE: --")
        self.ga_confidence.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        ga_layout.addWidget(self.ga_confidence)

        self.ga_actions = QLabel("ACTIONS: --")
        self.ga_actions.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        ga_layout.addWidget(self.ga_actions)

        layout.addWidget(self.ga_frame)
        self._hidden_widgets.append(self.ga_frame)

        # ── Quick Actions ────────────────────────────────────
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)

        self.optimize_btn = QPushButton("OPTIMIZE")
        self.optimize_btn.setFixedHeight(36)
        self.optimize_btn.setCursor(Qt.PointingHandCursor)
        self.optimize_btn.setStyleSheet(button_primary_style())
        self.optimize_btn.clicked.connect(lambda: self.navigate_to.emit("optimize"))
        actions_layout.addWidget(self.optimize_btn)

        self.benchmark_btn = QPushButton("BENCHMARK")
        self.benchmark_btn.setFixedHeight(36)
        self.benchmark_btn.setCursor(Qt.PointingHandCursor)
        self.benchmark_btn.setStyleSheet(button_secondary_style())
        self.benchmark_btn.clicked.connect(lambda: self.navigate_to.emit("tools"))
        actions_layout.addWidget(self.benchmark_btn)
        self._hidden_widgets.append(self.benchmark_btn)

        self.diagnostic_btn = QPushButton("DIAGNOSTIC")
        self.diagnostic_btn.setFixedHeight(36)
        self.diagnostic_btn.setCursor(Qt.PointingHandCursor)
        self.diagnostic_btn.setStyleSheet(button_secondary_style())
        self.diagnostic_btn.clicked.connect(lambda: self.navigate_to.emit("tools"))
        actions_layout.addWidget(self.diagnostic_btn)
        self._hidden_widgets.append(self.diagnostic_btn)

        actions_layout.addStretch()
        layout.addLayout(actions_layout)

        layout.addStretch()
