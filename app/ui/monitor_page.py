"""
Heaven Society — MONITOR Page

Real-time telemetry dashboard with compact metric cards.
Only shows metrics actually collected by the backend.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout,
    QProgressBar, QScrollArea
)
from PySide6.QtCore import Qt, QTimer

from app.ui.theme import (
    BG_PANEL, BORDER_LIGHT, BORDER_MEDIUM,
    ACCENT_PRIMARY, ACCENT_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    STATUS_OK, STATUS_WARN, STATUS_ERROR, STATUS_MUTED,
    FONT_FAMILY, FONT_MONO,
    FONT_SIZE_LG, FONT_SIZE_SM, FONT_SIZE_XS,
    WEIGHT_BOLD, WEIGHT_SEMIBOLD, WEIGHT_MEDIUM,
    RADIUS_MD, card_style, metric_color, temp_color,
    section_header_style, card_title_style, metric_title_style,
    metric_value_style, unit_label_style, status_indicator_style,
    no_data_style, loading_placeholder_style,
)
from app.core.telemetry import telemetry_engine
from app.performance.telemetry_dashboard import telemetry_dashboard, TimeRange
from app.utils.logger import get_logger
from app.ui.monitor_page_worker import MonitorWorkerThread, MonitorWorkerResult

logger = get_logger("ui.monitor_page")


class TelemetryCard(QFrame):
    """Compact real-time metric card with progress bar."""

    def __init__(self, title: str, unit: str = "%", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.NoFrame)
        self.setMinimumHeight(60)
        self.setMaximumHeight(68)
        self.setStyleSheet(f"""
            QFrame {{
                {card_style()}
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(metric_title_style())

        self.value_label = QLabel("--")
        self.value_label.setStyleSheet(metric_value_style())
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.unit_label = QLabel(unit)
        self.unit_label.setStyleSheet(unit_label_style())

        layout.addWidget(self.title_label)
        h = QHBoxLayout()
        h.setSpacing(3)
        h.addWidget(self.value_label)
        h.addWidget(self.unit_label)
        h.addStretch()
        layout.addLayout(h)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(2)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {BORDER_LIGHT};
                border-radius: 1px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {ACCENT_PRIMARY};
                border-radius: 1px;
            }}
        """)
        layout.addWidget(self.bar)

        # Sparkline label (lightweight history visualization)
        self.sparkline_label = QLabel("")
        self.sparkline_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_MONO};
            font-size: 9px;
            border: none;
            padding: 0;
        """)
        self.sparkline_label.setFixedHeight(12)
        layout.addWidget(self.sparkline_label)

    def update_value(self, value: float, color: str = TEXT_PRIMARY):
        # Skip expensive stylesheet rebuild if value unchanged
        rounded = round(value, 1)
        if hasattr(self, '_last_val') and self._last_val == rounded and self._last_color == color:
            return
        self._last_val = rounded
        self._last_color = color
        self.value_label.setText(f"{value:.1f}")
        self.value_label.setStyleSheet(metric_value_style(color))
        self.bar.setValue(int(min(100, max(0, value))))

    def set_na(self):
        if hasattr(self, '_last_val') and self._last_val is None:
            return
        self._last_val = None
        self._last_color = None
        self.value_label.setText("N/A")
        self.value_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_MEDIUM};
            border: none;
        """)
        self.bar.setValue(0)

    def update_sparkline(self, sparkline: str):
        """Update the lightweight sparkline display."""
        if sparkline:
            self.sparkline_label.setText(sparkline)
        else:
            self.sparkline_label.setText("")


class MonitorPage(QWidget):
    """Monitor page with real-time telemetry grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards = {}
        self._worker_thread: MonitorWorkerThread | None = None
        self._worker_count = 0
        self._pm_provider = None  # Cached PresentMonProvider
        self._last_bottleneck = None  # Cached bottleneck from worker
        self._setup_ui()
        # Telemetry: 2s for fast cached reads
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_telemetry)
        # Expensive diagnostics: 15s background worker
        self._diag_timer = QTimer(self)
        self._diag_timer.timeout.connect(self._start_worker)
        # Timers start in showEvent to avoid work when hidden

    def showEvent(self, event):
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(2000)
            self._update_telemetry()  # immediate refresh
        if not self._diag_timer.isActive():
            self._diag_timer.start(15000)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()
        self._diag_timer.stop()

    def _setup_ui(self):
        from PySide6.QtWidgets import QScrollArea as _SA
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = _SA()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        scroll.setWidget(scroll_content)
        outer.addWidget(scroll)

        title = QLabel("TELEMETRY")
        title.setStyleSheet(f"""
            color: {ACCENT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 2px;
            border: none;
        """)
        layout.addWidget(title)

        # System metrics grid
        sys_grid = QGridLayout()
        sys_grid.setSpacing(6)

        sys_metrics = [
            ("CPU", "%"), ("GPU", "%"), ("RAM", "%"), ("VRAM", "%"),
            ("GPU TEMP", "°C"), ("GPU CLOCK", "MHz"),
        ]
        for i, (name, unit) in enumerate(sys_metrics):
            card = TelemetryCard(name, unit)
            self._cards[name] = card
            sys_grid.addWidget(card, i // 3, i % 3)

        layout.addLayout(sys_grid)

        # FPS section
        fps_label = QLabel("FRAME TELEMETRY")
        fps_label.setStyleSheet(section_header_style())
        layout.addWidget(fps_label)

        fps_grid = QGridLayout()
        fps_grid.setSpacing(6)

        fps_metrics = [
            ("FPS", ""), ("1% LOW", ""), ("0.1% LOW", ""),
            ("FRAME TIME", "ms"), ("FRAME VARIANCE", "ms²"), ("SPIKES", ""),
        ]
        for i, (name, unit) in enumerate(fps_metrics):
            card = TelemetryCard(name, unit)
            self._cards[name] = card
            fps_grid.addWidget(card, i // 3, i % 3)

        layout.addLayout(fps_grid)

        # Responsiveness
        resp_frame = QFrame()
        resp_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        resp_layout = QVBoxLayout(resp_frame)
        resp_layout.setContentsMargins(10, 6, 10, 6)
        resp_layout.setSpacing(2)

        resp_header = QHBoxLayout()
        resp_title = QLabel("INPUT RESPONSIVENESS")
        resp_title.setStyleSheet(card_title_style())
        resp_header.addWidget(resp_title)
        resp_header.addStretch()
        self.resp_score_label = QLabel("")
        self.resp_score_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        resp_header.addWidget(self.resp_score_label)
        resp_layout.addLayout(resp_header)

        # Compact metrics
        resp_grid = QHBoxLayout()
        resp_grid.setSpacing(6)

        self.resp_level_label = QLabel("--")
        self.resp_level_label.setStyleSheet(f"""
            color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        resp_grid.addWidget(self.resp_level_label)

        self.resp_bottleneck_label = QLabel("")
        self.resp_bottleneck_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            border: none;
        """)
        resp_grid.addWidget(self.resp_bottleneck_label)
        resp_grid.addStretch()

        resp_layout.addLayout(resp_grid)

        # Recommendation text
        self.resp_rec_label = QLabel("")
        self.resp_rec_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            border: none;
        """)
        self.resp_rec_label.setWordWrap(True)
        resp_layout.addWidget(self.resp_rec_label)

        layout.addWidget(resp_frame)

        # Thermal
        thermal_frame = QFrame()
        thermal_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        thermal_layout = QVBoxLayout(thermal_frame)
        thermal_layout.setContentsMargins(10, 6, 10, 6)
        thermal_layout.setSpacing(2)

        thermal_header = QHBoxLayout()
        thermal_title = QLabel("THERMAL")
        thermal_title.setStyleSheet(card_title_style())
        thermal_header.addWidget(thermal_title)
        thermal_header.addStretch()
        self.thermal_state_label = QLabel("")
        self.thermal_state_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        thermal_header.addWidget(self.thermal_state_label)
        thermal_layout.addLayout(thermal_header)

        # GPU/CPU temps
        thermal_grid = QHBoxLayout()
        thermal_grid.setSpacing(6)

        self.thermal_gpu_label = QLabel("GPU TEMP")
        self.thermal_gpu_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.thermal_cpu_label = QLabel("CPU TEMP")
        self.thermal_cpu_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")
        self.thermal_throttle_label = QLabel("THROTTLE")
        self.thermal_throttle_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS}; border: none;")

        for lbl in [self.thermal_gpu_label, self.thermal_cpu_label, self.thermal_throttle_label]:
            thermal_grid.addWidget(lbl)
        thermal_layout.addLayout(thermal_grid)

        thermal_vals = QHBoxLayout()
        thermal_vals.setSpacing(6)

        self.thermal_gpu_val = QLabel("--")
        self.thermal_gpu_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.thermal_cpu_val = QLabel("--")
        self.thermal_cpu_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")
        self.thermal_throttle_val = QLabel("--")
        self.thermal_throttle_val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}; font-weight: {WEIGHT_BOLD}; border: none;")

        for lbl in [self.thermal_gpu_val, self.thermal_cpu_val, self.thermal_throttle_val]:
            thermal_vals.addWidget(lbl)
        thermal_layout.addLayout(thermal_vals)

        layout.addWidget(thermal_frame)

        # Bottleneck
        bn_frame = QFrame()
        bn_frame.setStyleSheet(f"""
            QFrame {{
                {card_style()}
            }}
        """)
        bn_layout = QVBoxLayout(bn_frame)
        bn_layout.setContentsMargins(10, 6, 10, 6)
        bn_layout.setSpacing(2)

        bn_header = QLabel("BOTTLENECK")
        bn_header.setStyleSheet(card_title_style())
        bn_layout.addWidget(bn_header)

        self.bottleneck_name = QLabel("ANALYZING...")
        self.bottleneck_name.setStyleSheet(f"""
            color: {TEXT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD};
            border: none;
        """)
        bn_layout.addWidget(self.bottleneck_name)

        self.bottleneck_detail = QLabel("")
        self.bottleneck_detail.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        bn_layout.addWidget(self.bottleneck_detail)

        layout.addWidget(bn_frame)
        layout.addStretch()

    def refresh(self):
        self._update_telemetry()
        self._start_worker()

    def _start_worker(self):
        """Start background worker for expensive diagnostics."""
        if self._worker_thread and self._worker_thread.isRunning():
            return
        self._worker_thread = MonitorWorkerThread(self)
        self._worker_thread.finished.connect(self._on_worker_result)
        self._worker_thread.error.connect(self._on_worker_error)
        self._worker_thread.start()

    def _on_worker_result(self, result: MonitorWorkerResult):
        """Apply background diagnostics results on GUI thread."""
        try:
            if result.input_latency_report:
                self._apply_input_latency(result.input_latency_report)
            if result.thermal_diag:
                self._apply_thermal(result.thermal_diag)
            if result.bottleneck_analysis:
                self._apply_bottleneck(result.bottleneck_analysis)
        except Exception as e:
            logger.debug(f"Monitor worker apply: {e}")
        self._worker_thread = None

    def _on_worker_error(self, msg: str):
        logger.debug(f"Monitor worker error: {msg}")
        self._worker_thread = None

    def _apply_input_latency(self, report):
        """Apply input latency results (from worker, safe on GUI thread)."""
        try:
            from app.performance.input_latency import ResponsivenessLevel
            score = report.responsiveness_score
            score_color = STATUS_OK
            if score < 50:
                score_color = STATUS_ERROR
            elif score < 70:
                score_color = STATUS_WARN
            self.resp_score_label.setText(f"{score:.0f}/100")
            self.resp_score_label.setStyleSheet(f"""
                color: {score_color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_XS};
                font-weight: {WEIGHT_BOLD}; border: none;
            """)
            level = report.responsiveness_level
            level_colors = {
                ResponsivenessLevel.EXCELLENT: STATUS_OK,
                ResponsivenessLevel.GOOD: STATUS_OK,
                ResponsivenessLevel.MODERATE: STATUS_WARN,
                ResponsivenessLevel.POOR: STATUS_ERROR,
                ResponsivenessLevel.CRITICAL: STATUS_ERROR,
                ResponsivenessLevel.INSUFFICIENT_DATA: STATUS_MUTED,
            }
            color = level_colors.get(level, TEXT_TERTIARY)
            self.resp_level_label.setText(level.value)
            self.resp_level_label.setStyleSheet(f"""
                color: {color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
                font-weight: {WEIGHT_BOLD}; border: none;
            """)
            bn_type = report.identified_bottleneck.value
            bn_conf = report.bottleneck_confidence * 100
            self.resp_bottleneck_label.setText(f"Bottleneck: {bn_type} ({bn_conf:.0f}%)")
            if report.recommendations:
                self.resp_rec_label.setText(report.recommendations[0])
            else:
                self.resp_rec_label.setText("No configuration changes needed")
        except Exception as e:
            logger.debug(f"Input latency apply: {e}")

    def _apply_thermal(self, diag):
        """Apply thermal diagnostics results (from worker, safe on GUI thread)."""
        try:
            from app.system.thermal_monitor import ThermalState, ThrottleIndicator
            state = diag.thermal_state
            state_colors = {
                ThermalState.COOL: STATUS_OK,
                ThermalState.WARM: STATUS_OK,
                ThermalState.HOT: STATUS_WARN,
                ThermalState.THROTTLING: STATUS_ERROR,
            }
            color = state_colors.get(state, TEXT_TERTIARY)
            self.thermal_state_label.setText(state.value)
            self.thermal_state_label.setStyleSheet(f"""
                color: {color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_XS};
                font-weight: {WEIGHT_BOLD}; border: none;
            """)
            throttle = diag.throttle_indicator
            throttle_colors = {
                ThrottleIndicator.NONE: STATUS_OK,
                ThrottleIndicator.LIGHT: STATUS_WARN,
                ThrottleIndicator.HEAVY: STATUS_ERROR,
            }
            t_color = throttle_colors.get(throttle, TEXT_TERTIARY)
            self.thermal_throttle_val.setText(throttle.value)
            self.thermal_throttle_val.setStyleSheet(f"""
                color: {t_color}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
                font-weight: {WEIGHT_BOLD}; border: none;
            """)
            if diag.cpu_temp:
                self.thermal_cpu_val.setText(f"{diag.cpu_temp:.0f}\u00b0C")
            if diag.gpu_temp:
                self.thermal_gpu_val.setText(f"{diag.gpu_temp:.0f}\u00b0C")
        except Exception as e:
            logger.debug(f"Thermal apply: {e}")

    def _apply_bottleneck(self, analysis):
        """Apply bottleneck results from background worker."""
        try:
            self._last_bottleneck = analysis
            if analysis.primary_bottleneck:
                bn = analysis.primary_bottleneck
                self.bottleneck_name.setText(bn.name.upper())
                if bn.severity in ("HIGH", "CRITICAL"):
                    color = STATUS_ERROR
                elif bn.severity == "MEDIUM":
                    color = STATUS_WARN
                else:
                    color = STATUS_OK
                self.bottleneck_name.setStyleSheet(f"""
                    color: {color};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD};
                    border: none;
                """)
                self.bottleneck_detail.setText(
                    f"{bn.confidence * 100:.0f}% confidence \u2014 {bn.description}"
                )
            else:
                self.bottleneck_name.setText("NO BOTTLENECK")
                self.bottleneck_name.setStyleSheet(f"""
                    color: {STATUS_OK};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD};
                    border: none;
                """)
                self.bottleneck_detail.setText("System appears balanced")
        except Exception as e:
            logger.debug(f"Bottleneck apply: {e}")

    def _update_telemetry(self):
        try:
            frame = telemetry_engine.current

            # Record into dashboard history buffers
            telemetry_dashboard.record_snapshot(frame)

            # CPU
            if frame.cpu_utilization > 0:
                self._cards["CPU"].update_value(
                    frame.cpu_utilization, metric_color(frame.cpu_utilization)
                )
                self._cards["CPU"].update_sparkline(
                    telemetry_dashboard.get_sparkline("cpu")
                )
            else:
                self._cards["CPU"].set_na()

            # GPU
            if frame.gpu_utilization > 0:
                self._cards["GPU"].update_value(
                    frame.gpu_utilization, metric_color(frame.gpu_utilization)
                )
            else:
                self._cards["GPU"].set_na()

            # RAM
            if frame.ram_percent > 0:
                self._cards["RAM"].update_value(
                    frame.ram_percent, metric_color(frame.ram_percent)
                )
                self._cards["RAM"].update_sparkline(
                    telemetry_dashboard.get_sparkline("ram")
                )
            else:
                self._cards["RAM"].set_na()

            # VRAM
            if frame.gpu_memory_total_mb > 0:
                vram_pct = (frame.gpu_memory_used_mb / frame.gpu_memory_total_mb) * 100
                self._cards["VRAM"].update_value(vram_pct, metric_color(vram_pct))
                self._cards["VRAM"].update_sparkline(
                    telemetry_dashboard.get_sparkline("vram")
                )
            else:
                self._cards["VRAM"].set_na()

            # GPU Temp
            if frame.gpu_temp is not None and frame.gpu_temp > 0:
                self._cards["GPU TEMP"].update_value(
                    frame.gpu_temp, temp_color(frame.gpu_temp)
                )
                self._cards["GPU TEMP"].update_sparkline(
                    telemetry_dashboard.get_sparkline("gpu_temp")
                )
            else:
                self._cards["GPU TEMP"].set_na()

            # GPU Clock
            if frame.gpu_clock_mhz and frame.gpu_clock_mhz > 0:
                self._cards["GPU CLOCK"].update_value(
                    frame.gpu_clock_mhz, TEXT_PRIMARY
                )
            else:
                self._cards["GPU CLOCK"].set_na()

            # FPS — PresentMon only
            try:
                from app.performance.presentmon_provider import PresentMonProvider
                if self._pm_provider is None:
                    self._pm_provider = PresentMonProvider()
                pm = self._pm_provider
                metrics = pm.get_metrics()
                if metrics.available and metrics.sample_count > 10:
                    # Record FPS into dashboard history
                    telemetry_dashboard.record_fps(
                        fps=metrics.avg_fps,
                        one_low=metrics.one_percent_low,
                        point_one_low=metrics.point_one_percent_low,
                        frame_time=metrics.avg_frame_time_ms,
                        frame_variance=metrics.frame_time_variance,
                    )
                    self._cards["FPS"].update_value(
                        metrics.avg_fps, metric_color(metrics.avg_fps)
                    )
                    self._cards["FPS"].update_sparkline(
                        telemetry_dashboard.get_sparkline("fps")
                    )
                    self._cards["1% LOW"].update_value(
                        metrics.one_percent_low, metric_color(metrics.one_percent_low)
                    )
                    self._cards["1% LOW"].update_sparkline(
                        telemetry_dashboard.get_sparkline("one_low")
                    )
                    self._cards["0.1% LOW"].update_value(
                        metrics.point_one_percent_low,
                        metric_color(metrics.point_one_percent_low),
                    )
                    self._cards["FRAME TIME"].update_value(
                        metrics.avg_frame_time_ms, TEXT_PRIMARY
                    )
                    self._cards["FRAME TIME"].update_sparkline(
                        telemetry_dashboard.get_sparkline("frame_time")
                    )
                    self._cards["FRAME VARIANCE"].update_value(
                        metrics.frame_time_variance, TEXT_PRIMARY
                    )
                    self._cards["SPIKES"].update_value(
                        metrics.frame_spikes,
                        STATUS_ERROR if metrics.frame_spikes > 20 else TEXT_PRIMARY,
                    )
                else:
                    self._cards["FPS"].set_na()
                    self._cards["1% LOW"].set_na()
                    self._cards["0.1% LOW"].set_na()
                    self._cards["FRAME TIME"].set_na()
                    self._cards["FRAME VARIANCE"].set_na()
                    self._cards["SPIKES"].set_na()
            except Exception:
                self._cards["FPS"].set_na()
                self._cards["1% LOW"].set_na()
                self._cards["0.1% LOW"].set_na()
                self._cards["FRAME TIME"].set_na()
                self._cards["FRAME VARIANCE"].set_na()
                self._cards["SPIKES"].set_na()

            # Bottleneck — use cached result from worker (avoid ~11ms on GUI thread)
            # Initial fallback before first worker result
            if self._last_bottleneck is None:
                from app.core.analyzer import bottleneck_analyzer
                self._last_bottleneck = bottleneck_analyzer.analyze(frame)
            analysis = self._last_bottleneck
            if analysis and analysis.primary_bottleneck:
                bn = analysis.primary_bottleneck
                self.bottleneck_name.setText(bn.name.upper())
                if bn.severity in ("HIGH", "CRITICAL"):
                    color = STATUS_ERROR
                elif bn.severity == "MEDIUM":
                    color = STATUS_WARN
                else:
                    color = STATUS_OK
                self.bottleneck_name.setStyleSheet(f"""
                    color: {color};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD};
                    border: none;
                """)
                self.bottleneck_detail.setText(
                    f"{bn.confidence * 100:.0f}% confidence \u2014 {bn.description}"
                )
            else:
                self.bottleneck_name.setText("NO BOTTLENECK")
                self.bottleneck_name.setStyleSheet(f"""
                    color: {STATUS_OK};
                    font-family: {FONT_FAMILY};
                    font-size: {FONT_SIZE_SM};
                    font-weight: {WEIGHT_BOLD};
                    border: none;
                """)
                self.bottleneck_detail.setText("System appears balanced")

            # Responsiveness and thermal are handled by background worker

        except Exception as e:
            logger.debug(f"Monitor update: {e}")


