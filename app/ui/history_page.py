"""
HISTORY page — past optimization sessions.
"""

import json
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton
)
from PySide6.QtCore import Qt

from app.utils.logger import get_logger

logger = get_logger("ui.history_page")

HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs", "optimization_history.jsonl"
)


class HistoryPage(QWidget):
    """History page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("HISTORY")
        title.setStyleSheet("color: #6478ff; font-size: 16px; font-weight: 700; letter-spacing: 2px;")
        layout.addWidget(title)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "DATE", "DURATION", "BEFORE", "AFTER", "CHANGES", "REVERTED"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0e0e16;
                color: #c8ccd4;
                border: 1px solid #1a1e28;
                border-radius: 6px;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #14141c;
                color: #5a6070;
                border: none;
                border-bottom: 1px solid #1a1e28;
                padding: 6px;
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 1px;
            }
        """)
        layout.addWidget(self.table)

        # Refresh button
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("REFRESH")
        refresh_btn.setFixedHeight(30)
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #14141c;
                color: #5a6070;
                border: 1px solid #1e2028;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                padding: 0 16px;
            }
            QPushButton:hover { background-color: #1a1e28; }
        """)
        refresh_btn.clicked.connect(self.refresh)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()

    def refresh(self):
        entries = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            entries.append(json.loads(line))
            except Exception as e:
                logger.error(f"Error reading history: {e}")

        self.table.setRowCount(len(entries))
        for i, entry in enumerate(reversed(entries)):
            self.table.setItem(i, 0, QTableWidgetItem(str(entry.get("timestamp", ""))[:19]))
            self.table.setItem(i, 1, QTableWidgetItem(f"{entry.get('duration_seconds', 0):.1f}s"))

            before = entry.get("before_score", "N/A")
            after = entry.get("after_score", "N/A")
            self.table.setItem(i, 2, QTableWidgetItem(str(before)))
            self.table.setItem(i, 3, QTableWidgetItem(str(after)))

            applied = entry.get("applied", [])
            reverted = entry.get("reverted", [])
            self.table.setItem(i, 4, QTableWidgetItem(f"{len(applied)} applied"))
            self.table.setItem(i, 5, QTableWidgetItem(f"{len(reverted)} reverted"))
