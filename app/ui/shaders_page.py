"""
SHADERS page — display/visual tuning with profile dropdown, sliders, and presets.
These modify display/emulator visual settings, NOT game files or memory.
"""

import json
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QComboBox, QPushButton, QGridLayout, QSlider
)
from PySide6.QtCore import Qt, Signal

from app.utils.logger import get_logger

logger = get_logger("ui.shaders_page")

SHADER_PRESETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "profiles", "shaders"
)

SHADER_PARAMS = [
    ("SATURATION", "saturation", 0, 200, 100),
    ("CONTRAST", "contrast", 0, 200, 100),
    ("SHARPNESS", "sharpness", 0, 100, 0),
    ("BLOOM", "bloom", 0, 100, 0),
    ("HDR", "hdr", 0, 100, 0),
    ("AMBIENT LIGHT", "ambient_light", 0, 100, 0),
    ("VIGNETTE", "vignette", 0, 100, 0),
    ("SHADOW", "shadow", -50, 50, 0),
]


class ShaderSlider(QFrame):
    """Compact horizontal slider with label and value display."""
    value_changed = Signal(str, int)

    def __init__(self, label: str, key: str, min_val: int, max_val: int, default: int, parent=None):
        super().__init__(parent)
        self.key = key
        self.default = default
        self.setFrameStyle(QFrame.NoFrame)
        self.setFixedHeight(36)
        self.setStyleSheet("QFrame { background-color: transparent; border: none; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Label
        self.label = QLabel(label)
        self.label.setFixedWidth(120)
        self.label.setStyleSheet("color: #5a6070; font-size: 11px; font-weight: 600; letter-spacing: 1px; border: none;")
        layout.addWidget(self.label)

        # Slider
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(min_val, max_val)
        self.slider.setValue(default)
        self.slider.setFixedHeight(20)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px;
                background: #1a1e28;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #6478ff;
                width: 14px;
                height: 14px;
                margin: -6px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #8b9cf7;
            }
            QSlider::sub-page:horizontal {
                background: #2d3555;
                border-radius: 2px;
            }
        """)
        self.slider.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self.slider, 1)

        # Value display
        self.value_label = QLabel(f"{default:03d}")
        self.value_label.setFixedWidth(36)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setStyleSheet("color: #6478ff; font-size: 12px; font-weight: 600; font-family: 'Consolas', monospace; border: none;")
        layout.addWidget(self.value_label)

    def _on_value_changed(self, val):
        self.value_label.setText(f"{val:03d}")
        self.value_changed.emit(self.key, val)

    def get_value(self) -> int:
        return self.slider.value()

    def set_value(self, val: int):
        self.slider.blockSignals(True)
        self.slider.setValue(val)
        self.value_label.setText(f"{val:03d}")
        self.slider.blockSignals(False)

    def reset(self):
        self.set_value(self.default)


class ShadersPage(QWidget):
    """Shaders page with profile dropdown, sliders, and controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_preset = "default"
        self._sliders = {}
        self._setup_ui()
        self._load_presets()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("VISUAL PROFILE")
        title.setStyleSheet("color: #6478ff; font-size: 16px; font-weight: 700; letter-spacing: 2px;")
        header_row.addWidget(title)
        header_row.addStretch()

        self.profile_combo = QComboBox()
        self.profile_combo.setFixedWidth(180)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        header_row.addWidget(self.profile_combo)
        layout.addLayout(header_row)

        # Note
        note = QLabel("PROFILE ONLY — Visual tuning parameters for emulator output. These save/load as profiles but do not modify game files or rendering.")
        note.setStyleSheet("color: #3a3e48; font-size: 10px; border: none; padding: 4px 0;")
        layout.addWidget(note)

        # Sliders container
        slider_frame = QFrame()
        slider_frame.setStyleSheet("""
            QFrame {
                background-color: #0e0e16;
                border: 1px solid #1a1e28;
                border-radius: 8px;
                padding: 16px;
            }
        """)
        slider_layout = QVBoxLayout(slider_frame)
        slider_layout.setContentsMargins(16, 12, 16, 12)
        slider_layout.setSpacing(4)

        for label, key, min_val, max_val, default in SHADER_PARAMS:
            slider = ShaderSlider(label, key, min_val, max_val, default)
            self._sliders[key] = slider
            slider_layout.addWidget(slider)

            # Separator between groups
            if key in ("contrast", "bloom", "ambient_light"):
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet("background-color: #1a1e28; border: none;")
                slider_layout.addWidget(sep)

        layout.addWidget(slider_frame)

        # Control buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        for text, callback, color in [
            ("RESET", self._reset, "#5a6070"),
            ("SAVE", self._apply, "#40c057"),
            ("SAVE PRESET", self._save_preset, "#6478ff"),
            ("LOAD PRESET", self._load_preset, "#6478ff"),
        ]:
            btn = QPushButton(text)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #14141c;
                    color: {color};
                    border: 1px solid #1e2028;
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: 600;
                    padding: 0 16px;
                    letter-spacing: 1px;
                }}
                QPushButton:hover {{
                    background-color: #1a1e28;
                    border-color: #2a2e38;
                }}
            """)
            btn.clicked.connect(callback)
            btn_layout.addWidget(btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()

    def _load_presets(self):
        """Load shader presets from JSON files."""
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self._presets = {}

        if os.path.exists(SHADER_PRESETS_DIR):
            for fname in sorted(os.listdir(SHADER_PRESETS_DIR)):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(SHADER_PRESETS_DIR, fname), "r") as f:
                            data = json.load(f)
                        name = data.get("name", fname.replace(".json", ""))
                        key = fname.replace(".json", "")
                        self._presets[key] = data
                        self.profile_combo.addItem(name, key)
                    except Exception as e:
                        logger.debug(f"Failed to load shader preset {fname}: {e}")

        self.profile_combo.blockSignals(False)

    def _on_profile_changed(self, text):
        key = self.profile_combo.currentData()
        if key and key in self._presets:
            self._current_preset = key
            data = self._presets[key]
            for slider_key, slider in self._sliders.items():
                if slider_key in data:
                    slider.set_value(data[slider_key])
            logger.debug(f"Loaded shader preset: {text}")

    def _reset(self):
        for slider in self._sliders.values():
            slider.reset()

    def _apply(self):
        values = {key: slider.get_value() for key, slider in self._sliders.items()}
        logger.info(f"Shader values applied: {values}")
        # Apply via display/emulator visual configuration
        # Actual implementation depends on emulator support

    def _save_preset(self):
        values = {key: slider.get_value() for key, slider in self._sliders.items()}
        values["name"] = "Custom"
        values["description"] = "User-defined shader configuration"

        custom_path = os.path.join(SHADER_PRESETS_DIR, "custom.json")
        try:
            os.makedirs(SHADER_PRESETS_DIR, exist_ok=True)
            with open(custom_path, "w") as f:
                json.dump(values, f, indent=2)
            self._load_presets()
            logger.info("Custom shader preset saved")
        except Exception as e:
            logger.error(f"Failed to save preset: {e}")

    def _load_preset(self):
        self._on_profile_changed(self.profile_combo.currentText())

    def refresh(self):
        pass
