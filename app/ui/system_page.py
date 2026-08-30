"""
System information page — CPU, memory, storage, and OS details.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QGridLayout, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt

from app.core.scanner import hardware_scanner
from app.utils.logger import get_logger

logger = get_logger("ui.system_page")


class SystemPage(QWidget):
    """System hardware information page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("SYSTEM INFORMATION")
        header.setStyleSheet("color: #e74c3c; font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        # CPU Info
        self.cpu_group = QGroupBox("CPU")
        self.cpu_group.setStyleSheet("QGroupBox { color: #ecf0f1; font-weight: bold; font-size: 13px; border: 1px solid #34495e; border-radius: 5px; margin-top: 10px; padding-top: 15px; }")
        cpu_layout = QGridLayout()
        self.cpu_labels = {}
        for i, (key, label) in enumerate([
            ("model", "Model"), ("cores", "Physical Cores"),
            ("threads", "Logical Processors"), ("max_freq", "Max Frequency"),
            ("arch", "Architecture"), ("cache", "L3 Cache"),
        ]):
            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet("color: #95a5a6;")
            val = QLabel("--")
            val.setStyleSheet("color: #ecf0f1;")
            cpu_layout.addWidget(lbl, i, 0)
            cpu_layout.addWidget(val, i, 1)
            self.cpu_labels[key] = val
        self.cpu_group.setLayout(cpu_layout)
        layout.addWidget(self.cpu_group)

        # Memory Info
        self.mem_group = QGroupBox("MEMORY")
        self.mem_group.setStyleSheet(self.cpu_group.styleSheet())
        mem_layout = QGridLayout()
        self.mem_labels = {}
        for i, (key, label) in enumerate([
            ("total", "Total RAM"), ("used", "Used RAM"),
            ("available", "Available RAM"), ("utilization", "Utilization"),
            ("swap_total", "Swap Total"), ("swap_used", "Swap Used"),
        ]):
            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet("color: #95a5a6;")
            val = QLabel("--")
            val.setStyleSheet("color: #ecf0f1;")
            mem_layout.addWidget(lbl, i, 0)
            mem_layout.addWidget(val, i, 1)
            self.mem_labels[key] = val
        self.mem_group.setLayout(mem_layout)
        layout.addWidget(self.mem_group)

        # Storage
        self.storage_group = QGroupBox("STORAGE")
        self.storage_group.setStyleSheet(self.cpu_group.styleSheet())
        storage_layout = QVBoxLayout()
        self.storage_table = QTableWidget(0, 4)
        self.storage_table.setHorizontalHeaderLabels(["Device", "Mount", "Total", "Free"])
        self.storage_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.storage_table.setStyleSheet("QTableWidget { background-color: #1a1a2e; color: #ecf0f1; border: 1px solid #34495e; } QHeaderView::section { background-color: #2c3e50; color: #ecf0f1; }")
        storage_layout.addWidget(self.storage_table)
        self.storage_group.setLayout(storage_layout)
        layout.addWidget(self.storage_group)

        layout.addStretch()

    def refresh(self):
        """Refresh system information display."""
        try:
            profile = hardware_scanner.scan()

            if profile.cpu:
                c = profile.cpu
                self.cpu_labels["model"].setText(c.model)
                self.cpu_labels["cores"].setText(str(c.physical_cores))
                self.cpu_labels["threads"].setText(str(c.logical_cores))
                self.cpu_labels["max_freq"].setText(f"{c.max_frequency_mhz:.0f} MHz")
                self.cpu_labels["arch"].setText(c.architecture)
                self.cpu_labels["cache"].setText(f"{c.l3_cache_size // 1024} KB" if c.l3_cache_size else "N/A")

            if profile.memory:
                m = profile.memory
                self.mem_labels["total"].setText(f"{m.ram_total_gb:.1f} GB")
                self.mem_labels["used"].setText(f"{m.ram_used_gb:.1f} GB")
                self.mem_labels["available"].setText(f"{m.ram_available_gb:.1f} GB")
                self.mem_labels["utilization"].setText(f"{m.ram_percent:.1f}%")
                self.mem_labels["swap_total"].setText(f"{m.swap_total_gb:.1f} GB")
                self.mem_labels["swap_used"].setText(f"{m.swap_used_gb:.1f} GB")

            self.storage_table.setRowCount(len(profile.storage))
            for i, s in enumerate(profile.storage):
                self.storage_table.setItem(i, 0, QTableWidgetItem(s.device_name))
                self.storage_table.setItem(i, 1, QTableWidgetItem(s.mount_point))
                self.storage_table.setItem(i, 2, QTableWidgetItem(f"{s.total_gb:.1f} GB"))
                self.storage_table.setItem(i, 3, QTableWidgetItem(f"{s.free_gb:.1f} GB"))

        except Exception as e:
            logger.error(f"System page refresh error: {e}")
