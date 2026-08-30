"""
GPU information page — vendor, model, VRAM, utilization, temperature.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGridLayout, QGroupBox, QFrame
)
from PySide6.QtCore import Qt

from app.core.scanner import hardware_scanner
from app.core.telemetry import telemetry_engine
from app.utils.logger import get_logger

logger = get_logger("ui.gpu_page")


class GPUPage(QWidget):
    """GPU information page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("GPU INFORMATION")
        header.setStyleSheet("color: #e74c3c; font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        self.gpu_info_frame = QFrame()
        self.gpu_info_frame.setStyleSheet("QFrame { background-color: #1a1a2e; border: 1px solid #34495e; border-radius: 8px; padding: 15px; }")
        self.gpu_layout = QGridLayout(self.gpu_info_frame)
        self.gpu_layout.setSpacing(8)

        self.gpu_labels = {}
        for i, (key, label) in enumerate([
            ("name", "GPU Name"), ("vendor", "Vendor"),
            ("type", "Type"), ("driver", "Driver Version"),
            ("vram", "VRAM"), ("util", "Utilization"),
            ("clock", "Core Clock"), ("mem_clock", "Memory Clock"),
            ("temp", "Temperature"), ("power", "Power Draw"),
            ("power_limit", "Power Limit"), ("power_state", "Power State"),
            ("fan", "Fan Speed"), ("cuda", "CUDA"),
            ("compute", "Compute Capability"),
        ]):
            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet("color: #95a5a6; font-size: 12px;")
            val = QLabel("--")
            val.setStyleSheet("color: #ecf0f1; font-size: 12px;")
            self.gpu_layout.addWidget(lbl, i, 0)
            self.gpu_layout.addWidget(val, i, 1)
            self.gpu_labels[key] = val

        layout.addWidget(self.gpu_info_frame)
        layout.addStretch()

    def refresh(self):
        """Refresh GPU information."""
        try:
            profile = hardware_scanner.scan()
            gpus = profile.gpus

            if gpus:
                gpu = gpus[0]
                gpu_type = "Discrete" if gpu.is_discrete else ("Integrated" if gpu.is_integrated else "Unknown")
                self.gpu_labels["name"].setText(gpu.name)
                self.gpu_labels["vendor"].setText(gpu.vendor)
                self.gpu_labels["type"].setText(gpu_type)
                self.gpu_labels["driver"].setText(gpu.driver_version)
                self.gpu_labels["vram"].setText(f"{gpu.vram_total_mb:.0f} MB" if gpu.vram_total_mb > 0 else "N/A")
                self.gpu_labels["cuda"].setText(f"Yes ({gpu.compute_capability})" if gpu.supports_cuda else "No")
                self.gpu_labels["compute"].setText(gpu.compute_capability or "N/A")

                # Dynamic values
                frame = telemetry_engine.current
                self.gpu_labels["util"].setText(f"{frame.gpu_utilization:.1f}%")
                self.gpu_labels["clock"].setText(f"{gpu.clock_core_mhz:.0f} MHz" if gpu.clock_core_mhz else "N/A")
                self.gpu_labels["mem_clock"].setText(f"{gpu.clock_memory_mhz:.0f} MHz" if gpu.clock_memory_mhz else "N/A")
                self.gpu_labels["temp"].setText(f"{gpu.temperature_celsius:.0f}°C" if gpu.temperature_celsius else "N/A")
                self.gpu_labels["power"].setText(f"{gpu.power_draw_watts:.1f}W" if gpu.power_draw_watts else "N/A")
                self.gpu_labels["power_limit"].setText(f"{gpu.power_limit_watts:.0f}W" if gpu.power_limit_watts else "N/A")
                self.gpu_labels["power_state"].setText(gpu.power_state)
                self.gpu_labels["fan"].setText(f"{gpu.fan_speed_percent:.0f}%" if gpu.fan_speed_percent is not None else "N/A")
            else:
                self.gpu_labels["name"].setText("No GPU Detected")

        except Exception as e:
            logger.error(f"GPU page refresh error: {e}")
