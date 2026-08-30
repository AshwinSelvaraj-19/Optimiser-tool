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

        layout.addWidget(self.title_label)
        h = QHBoxLayout()
        h.setSpacing(3)
        h.addWidget(self.value_label)
        h.addWidget(self.unit_label)
        h.addStretch()
        layout.addLayout(h)

    def set_value(self, value: str, color: str = TEXT_PRIMARY, unit: str = ""):
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
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(1500)

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

        self.diagnostic_btn = QPushButton("DIAGNOSTIC")
        self.diagnostic_btn.setFixedHeight(36)
        self.diagnostic_btn.setCursor(Qt.PointingHandCursor)
        self.diagnostic_btn.setStyleSheet(button_secondary_style())
        self.diagnostic_btn.clicked.connect(lambda: self.navigate_to.emit("tools"))
        actions_layout.addWidget(self.diagnostic_btn)

        actions_layout.addStretch()
        layout.addLayout(actions_layout)

        layout.addStretch()

    def refresh(self):
        self._update()

    def _update(self):
        self._update_target()
        self._update_metrics()
        self._update_status()
        self._update_gaming_analysis()

    def _update_target(self):
        """Detect emulator and update target panel."""
        try:
            from app.performance.target_process import target_process_detector
            candidates = target_process_detector.get_candidates()
            if candidates:
                best = target_process_detector.select_best_target()
                if best:
                    # Get GPU info
                    gpu_name = "--"
                    try:
                        from app.performance.gpu_association import gpu_association_detector
                        assoc = gpu_association_detector.detect_for_process(
                            best.process_name, best.pid
                        )
                        if assoc.gpu_name:
                            gpu_name = assoc.gpu_name
                    except Exception:
                        pass

                    self.target_panel.set_detected(
                        name=best.emulator,
                        process=best.process_name,
                        pid=best.pid,
                        gpu=gpu_name,
                    )
                    return
            self.target_panel.set_not_detected()
        except Exception as e:
            logger.debug(f"Target detection: {e}")
            self.target_panel.set_not_detected()

    def _update_metrics(self):
        """Update all metric blocks from real telemetry."""
        try:
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current

            # CPU
            if frame.cpu_utilization > 0:
                self.cpu_block.set_value(
                    f"{frame.cpu_utilization:.0f}",
                    color=metric_color(frame.cpu_utilization),
                    unit="%"
                )
            else:
                self.cpu_block.set_value("--", color=TEXT_TERTIARY)

            # GPU
            if frame.gpu_utilization > 0:
                self.gpu_block.set_value(
                    f"{frame.gpu_utilization:.0f}",
                    color=metric_color(frame.gpu_utilization),
                    unit="%"
                )
            else:
                self.gpu_block.set_value("--", color=TEXT_TERTIARY)

            # RAM
            if frame.ram_percent > 0:
                self.ram_block.set_value(
                    f"{frame.ram_percent:.0f}",
                    color=metric_color(frame.ram_percent),
                    unit="%"
                )
            else:
                self.ram_block.set_value("--", color=TEXT_TERTIARY)

            # GPU Temp
            if frame.gpu_temp is not None and frame.gpu_temp > 0:
                self.temp_block.set_value(
                    f"{frame.gpu_temp:.0f}",
                    color=temp_color(frame.gpu_temp),
                    unit="°C"
                )
            else:
                self.temp_block.set_value("N/A", color=TEXT_TERTIARY)

            # FPS — only from PresentMon, never fabricated
            self._update_fps()

        except Exception as e:
            logger.debug(f"Metrics update: {e}")

    def _update_fps(self):
        """Update FPS display from PresentMon only."""
        try:
            from app.performance.presentmon_provider import find_presentmon
            pm_path = find_presentmon()

            if not pm_path:
                self.fps_block.set_value("N/A", color=TEXT_TERTIARY)
                self.one_low_block.set_value("N/A", color=TEXT_TERTIARY)
                self.frame_time_block.set_value("N/A", color=TEXT_TERTIARY)
                self.stability_block.set_value("--", color=TEXT_TERTIARY)
                return

            # PresentMon is available but not currently capturing
            self.fps_block.set_value("--", color=STATUS_MUTED)
            self.one_low_block.set_value("--", color=STATUS_MUTED)
            self.frame_time_block.set_value("--", color=STATUS_MUTED)
            self.stability_block.set_value("--", color=STATUS_MUTED)

        except Exception as e:
            logger.debug(f"FPS update: {e}")

    def _update_status(self):
        """Update performance status and PresentMon indicator."""
        try:
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current

            # Performance status based on real data
            if frame.cpu_utilization <= 0 and frame.gpu_utilization <= 0:
                self.perf_status.setText("IDLE")
                self.perf_status.setStyleSheet(f"""
                    color: {STATUS_MUTED};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD};
                    border: none;
                """)
            elif frame.gpu_utilization > 90:
                self.perf_status.setText("GPU LIMITED")
                self.perf_status.setStyleSheet(f"""
                    color: {STATUS_ERROR};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD};
                    border: none;
                """)
            elif frame.cpu_utilization > 90:
                self.perf_status.setText("CPU LIMITED")
                self.perf_status.setStyleSheet(f"""
                    color: {STATUS_WARN};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD};
                    border: none;
                """)
            elif frame.gpu_temp and frame.gpu_temp > 85:
                self.perf_status.setText("THERMAL WARNING")
                self.perf_status.setStyleSheet(f"""
                    color: {STATUS_ERROR};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD};
                    border: none;
                """)
            else:
                self.perf_status.setText("STABLE")
                self.perf_status.setStyleSheet(f"""
                    color: {STATUS_OK};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD};
                    border: none;
                """)

            # PresentMon status
            from app.performance.presentmon_provider import find_presentmon
            pm_path = find_presentmon()
            if pm_path:
                self.pm_status.setText("PresentMon ● READY")
                self.pm_status.setStyleSheet(f"""
                    color: {STATUS_OK};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_XS};
                    border: none;
                """)
            else:
                self.pm_status.setText("PresentMon ● UNAVAILABLE")
                self.pm_status.setStyleSheet(f"""
                    color: {STATUS_ERROR};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_XS};
                    border: none;
                """)

            # Hardware class
            try:
                from app.core.hardware_profile import analyze_hardware_profile
                prof = analyze_hardware_profile()
                self.hw_class_label.setText(prof.system_tier.value.upper())
            except Exception:
                self.hw_class_label.setText("")

        except Exception as e:
            logger.debug(f"Status update: {e}")

    def _update_gaming_analysis(self):
        """Update compact gaming analysis section."""
        try:
            from app.core.adaptive_optimizer import adaptive_optimizer
            decision = adaptive_optimizer.analyze()

            # Bottleneck
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
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_XS};
                border: none;
            """)

            # Confidence
            conf_pct = f"{decision.bottleneck_confidence:.0%}"
            self.ga_confidence.setText(f"CONFIDENCE: {conf_pct}")

            # Actions
            applicable = sum(1 for o in decision.recommended_optimizations if o.status == "APPLICABLE")
            total = len(decision.recommended_optimizations)
            self.ga_actions.setText(f"ACTIONS: {applicable}/{total}")

        except Exception as e:
            logger.debug(f"Gaming analysis update: {e}")
