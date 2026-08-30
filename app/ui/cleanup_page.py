"""
Heaven Society — CLEANUP Page

Compact system cleanup with real-time scan results.
Silver + Red premium gaming aesthetic.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QScrollArea, QProgressBar, QCheckBox, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal

from app.ui.theme import (
    BG_PANEL, BORDER_LIGHT, ACCENT_PRIMARY, ACCENT_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY, TEXT_INVERSE,
    STATUS_OK, STATUS_WARN, STATUS_ERROR, STATUS_MUTED,
    FONT_FAMILY, FONT_MONO,
    FONT_SIZE_SM, FONT_SIZE_XS,
    WEIGHT_BOLD, WEIGHT_SEMIBOLD, WEIGHT_MEDIUM,
    RADIUS_MD, card_style, button_primary_style, button_secondary_style,
)
from app.utils.logger import get_logger

logger = get_logger("ui.cleanup_page")


class ScanThread(QThread):
    """Background scan thread."""
    complete = Signal(object)

    def run(self):
        from app.cleanup.cleanup_scanner import CleanupScanner
        scanner = CleanupScanner()
        items = scanner.scan()
        self.complete.emit(items)


class CleanThread(QThread):
    """Background cleanup thread."""
    progress = Signal(float, str)
    complete = Signal(object)

    def __init__(self, items):
        super().__init__()
        self.items = items

    def run(self):
        from app.cleanup.cleanup_engine import CleanupEngine
        engine = CleanupEngine()
        result = engine.clean(self.items, progress_callback=lambda p, m: self.progress.emit(p, m))
        self.complete.emit(result)


class CleanupItemRow(QFrame):
    """Compact cleanup item display with checkbox."""

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self.setFrameStyle(QFrame.NoFrame)
        self.setFixedHeight(36)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_LIGHT};
                border-radius: {RADIUS_MD};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)

        # Checkbox
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(item.selected and item.can_delete)
        self.checkbox.setEnabled(item.can_delete)
        self.checkbox.setFixedWidth(20)
        self.checkbox.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid {BORDER_LIGHT};
                background-color: {BG_PANEL};
            }}
            QCheckBox::indicator:checked {{
                background-color: {ACCENT_PRIMARY};
                border-color: {ACCENT_PRIMARY};
            }}
            QCheckBox::indicator:disabled {{
                background-color: {BORDER_LIGHT};
                border-color: {BORDER_LIGHT};
            }}
        """)
        layout.addWidget(self.checkbox)

        # Name + description
        info_layout = QVBoxLayout()
        info_layout.setSpacing(1)

        self.name_label = QLabel(item.name)
        self.name_label.setStyleSheet(f"""
            color: {TEXT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_SEMIBOLD};
            border: none;
        """)
        info_layout.addWidget(self.name_label)

        self.desc_label = QLabel(item.description.split('\n')[0] if item.description else "")
        self.desc_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            border: none;
        """)
        info_layout.addWidget(self.desc_label)

        layout.addLayout(info_layout, 1)

        # Size
        self.size_label = QLabel(item.removable_display)
        self.size_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_MEDIUM};
            border: none;
        """)
        self.size_label.setFixedWidth(70)
        self.size_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.size_label)

        # Status
        status_text = ""
        status_color = TEXT_TERTIARY
        if item.status and item.status.value:
            status_text = item.status.value
            if item.status.value == "AVAILABLE":
                status_color = STATUS_OK
            elif item.status.value == "REQUIRES_ADMIN":
                status_color = STATUS_WARN
            elif item.status.value == "RECOMMENDATION ONLY":
                status_color = STATUS_MUTED
            elif item.status.value == "NOT AVAILABLE":
                status_color = STATUS_MUTED

        self.status_label = QLabel(status_text)
        self.status_label.setStyleSheet(f"""
            color: {status_color};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_SEMIBOLD};
            border: none;
        """)
        self.status_label.setFixedWidth(100)
        layout.addWidget(self.status_label)


class CleanupPage(QWidget):
    """Cleanup page — compact Heaven Society cleanup utility."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._item_rows = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # ── Header ──────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("CLEANUP")
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

        self.scan_btn = QPushButton("SCAN")
        self.scan_btn.setFixedHeight(32)
        self.scan_btn.setCursor(Qt.PointingHandCursor)
        self.scan_btn.setStyleSheet(button_secondary_style())
        self.scan_btn.clicked.connect(self._start_scan)
        header.addWidget(self.scan_btn)

        self.clean_btn = QPushButton("CLEAN SELECTED")
        self.clean_btn.setFixedHeight(32)
        self.clean_btn.setCursor(Qt.PointingHandCursor)
        self.clean_btn.setStyleSheet(button_primary_style())
        self.clean_btn.setEnabled(False)
        self.clean_btn.clicked.connect(self._start_clean)
        header.addWidget(self.clean_btn)

        layout.addLayout(header)

        # ── Summary Card ────────────────────────────────────
        summary_frame = QFrame()
        summary_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(12, 8, 12, 8)
        summary_layout.setSpacing(4)

        summary_title = QLabel("SYSTEM CLEANUP")
        summary_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        summary_layout.addWidget(summary_title)

        self.summary_text = QLabel("Scan to detect cleanup targets...")
        self.summary_text.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_SM};
            border: none;
        """)
        self.summary_text.setWordWrap(True)
        summary_layout.addWidget(self.summary_text)

        self.total_reclaimable = QLabel("")
        self.total_reclaimable.setStyleSheet(f"""
            color: {ACCENT_PRIMARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD};
            border: none;
        """)
        summary_layout.addWidget(self.total_reclaimable)

        layout.addWidget(summary_frame)

        # ── Disk Status Card ─────────────────────────────────
        disk_frame = QFrame()
        disk_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        disk_layout = QVBoxLayout(disk_frame)
        disk_layout.setContentsMargins(12, 8, 12, 8)
        disk_layout.setSpacing(3)

        disk_header = QHBoxLayout()
        disk_title = QLabel("DISK STATUS")
        disk_title.setStyleSheet(f"""
            color: {TEXT_TERTIARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD};
            letter-spacing: 1px;
            border: none;
        """)
        disk_header.addWidget(disk_title)
        disk_header.addStretch()
        self.disk_pressure_label = QLabel("")
        self.disk_pressure_label.setStyleSheet(f"""
            color: {TEXT_TERTIARY}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        disk_header.addWidget(self.disk_pressure_label)
        disk_layout.addLayout(disk_header)

        # Drive info
        disk_grid = QHBoxLayout()
        disk_grid.setSpacing(6)

        self.disk_drive_label = QLabel("--")
        self.disk_drive_label.setStyleSheet(f"""
            color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        disk_grid.addWidget(self.disk_drive_label)

        self.disk_free_label = QLabel("--")
        self.disk_free_label.setStyleSheet(f"""
            color: {TEXT_PRIMARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD}; border: none;
        """)
        disk_grid.addWidget(self.disk_free_label)

        self.disk_type_label = QLabel("--")
        self.disk_type_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_XS};
            border: none;
        """)
        disk_grid.addWidget(self.disk_type_label)

        disk_layout.addLayout(disk_grid)

        layout.addWidget(disk_frame)

        # ── Progress ────────────────────────────────────────
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

        # ── Items List ──────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        self.items_container = QWidget()
        self.items_layout = QVBoxLayout(self.items_container)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(3)
        self.items_layout.addStretch()

        scroll.setWidget(self.items_container)
        layout.addWidget(scroll, 1)

        # ── Result Card ─────────────────────────────────────
        self.result_frame = QFrame()
        self.result_frame.setStyleSheet(f"QFrame {{ {card_style()} }}")
        self.result_frame.setVisible(False)
        result_layout = QVBoxLayout(self.result_frame)
        result_layout.setContentsMargins(12, 8, 12, 8)
        result_layout.setSpacing(4)

        self.result_title = QLabel("CLEANUP COMPLETE")
        self.result_title.setStyleSheet(f"""
            color: {STATUS_OK};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD};
            border: none;
        """)
        result_layout.addWidget(self.result_title)

        self.result_text = QLabel("")
        self.result_text.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_SM};
            border: none;
        """)
        self.result_text.setWordWrap(True)
        result_layout.addWidget(self.result_text)

        layout.addWidget(self.result_frame)

    def refresh(self):
        self._load_disk_status()

    def _load_disk_status(self):
        """Load disk diagnostics into the compact section."""
        try:
            from app.system.disk_analyzer import disk_analyzer, StoragePressure
            from app.cleanup.cleanup_models import format_bytes

            diag = disk_analyzer.diagnose()

            # Update pressure
            pressure_colors = {
                StoragePressure.NORMAL: STATUS_OK,
                StoragePressure.LOW_SPACE: STATUS_WARN,
                StoragePressure.HIGH_PRESSURE: STATUS_ERROR,
                StoragePressure.CRITICAL: STATUS_ERROR,
            }
            color = pressure_colors.get(diag.pressure_level, TEXT_TERTIARY)
            self.disk_pressure_label.setText(diag.pressure_level.value)
            self.disk_pressure_label.setStyleSheet(f"""
                color: {color}; font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_XS};
                font-weight: {WEIGHT_BOLD}; border: none;
            """)

            # Update drive info
            if diag.system_drive:
                d = diag.system_drive
                free_pct = 100 - d.percent_used
                free_gb = d.free_bytes / (1024 ** 3)
                self.disk_drive_label.setText(f"{d.mountpoint}  {format_bytes(d.used_bytes)}/{format_bytes(d.total_bytes)}")
                self.disk_free_label.setText(f"{free_gb:.1f}GB free ({free_pct:.0f}%)")
                self.disk_type_label.setText(d.disk_type if d.disk_type != "UNKNOWN" else "")
            else:
                self.disk_drive_label.setText("No system drive detected")
                self.disk_free_label.setText("")
                self.disk_type_label.setText("")

        except Exception as e:
            logger.debug(f"Disk status load: {e}")

    def _start_scan(self):
        """Start background scan."""
        self.scan_btn.setEnabled(False)
        self.clean_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Scanning...")
        self.result_frame.setVisible(False)
        self._clear_items()

        self._scan_thread = ScanThread()
        self._scan_thread.complete.connect(self._on_scan_complete)
        self._scan_thread.start()

    def _on_scan_complete(self, items):
        """Handle scan completion."""
        self._items = items
        self.scan_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.progress_label.setText("")
        self._load_disk_status()

        # Populate items
        self._clear_items()
        from app.cleanup.cleanup_models import CleanupCategory

        for item in items:
            row = CleanupItemRow(item)
            row.checkbox.stateChanged.connect(
                lambda state, it=item: self._on_item_toggled(it, state)
            )
            self._item_rows.append(row)
            self.items_layout.insertWidget(self.items_layout.count() - 1, row)

        # Update summary
        total_removable = sum(i.removable_size for i in items if i.can_delete)
        total_files = sum(i.removable_file_count for i in items if i.can_delete)
        admin_count = sum(1 for i in items if i.requires_admin)
        rec_count = sum(1 for i in items if i.status and i.status.value == "RECOMMENDATION ONLY")

        self.summary_text.setText(
            f"{len(items)} targets detected  •  "
            f"{total_files:,} removable files  •  "
            f"{admin_count} require admin  •  "
            f"{rec_count} recommendation-only"
        )

        from app.cleanup.cleanup_models import format_bytes
        self.total_reclaimable.setText(f"Potentially reclaimable: {format_bytes(total_removable)}")

        self._update_clean_button()

    def _on_item_toggled(self, item, state):
        """Handle item checkbox toggle."""
        item.selected = (state == Qt.Checked.value)
        self._update_clean_button()

    def _update_clean_button(self):
        """Enable clean button if any items are selected."""
        any_selected = any(i.selected and i.can_delete for i in self._items)
        self.clean_btn.setEnabled(any_selected)

    def _start_clean(self):
        """Start background cleanup."""
        self.clean_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.result_frame.setVisible(False)

        selected = [i for i in self._items if i.selected and i.can_delete]
        self._clean_thread = CleanThread(selected)
        self._clean_thread.progress.connect(self._on_clean_progress)
        self._clean_thread.complete.connect(self._on_clean_complete)
        self._clean_thread.start()

    def _on_clean_progress(self, pct, msg):
        self.progress_bar.setValue(int(pct))
        self.progress_label.setText(msg)

    def _on_clean_complete(self, session):
        """Handle cleanup completion."""
        self.scan_btn.setEnabled(True)
        self.clean_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self.progress_label.setText("")

        # Show result
        self.result_frame.setVisible(True)

        if session.success:
            self.result_title.setText("CLEANUP COMPLETE")
            self.result_title.setStyleSheet(f"""
                color: {STATUS_OK};
                font-family: {FONT_FAMILY};
                font-size: {FONT_SIZE_SM};
                font-weight: {WEIGHT_BOLD};
                border: none;
            """)
        else:
            self.result_title.setText("CLEANUP COMPLETE (partial)")
            self.result_title.setStyleSheet(f"""
                color: {STATUS_WARN};
                font-family: {FONT_FAMILY};
                font-size: {FONT_SIZE_SM};
                font-weight: {WEIGHT_BOLD};
                border: none;
            """)

        from app.cleanup.cleanup_models import format_bytes
        self.result_text.setText(
            f"Freed: {format_bytes(session.bytes_freed)}\n"
            f"Deleted: {session.files_deleted:,} files\n"
            f"Skipped: {session.failed_items} items\n"
            f"Verification: {'PASSED' if session.verification_failed == 0 else 'PARTIAL'}"
        )

        # Re-scan to show updated state
        self._start_scan()

    def _clear_items(self):
        """Clear all item rows."""
        while self.items_layout.count() > 1:
            item = self.items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._item_rows.clear()
