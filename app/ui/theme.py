"""
Heaven Society — UI Theme System

Silver + Red premium gaming aesthetic.
Compact, modern, lightweight design tokens.
"""

# ============================================================
# COLOR SYSTEM
# ============================================================

# Backgrounds
BG_PRIMARY = "#f0f0f4"       # Main window background — light silver
BG_PANEL = "#ffffff"          # Cards/panels — white
BG_PANEL_HOVER = "#f7f7fa"   # Panel hover state
BG_ELEVATED = "#fafafa"       # Elevated surfaces
BG_INPUT = "#f0f0f4"          # Input/combobox backgrounds

# Borders
BORDER_LIGHT = "#e2e2e8"      # Subtle borders
BORDER_MEDIUM = "#d0d0d8"     # Medium borders
BORDER_FOCUS = "#c41e3a"      # Focus/active borders

# Text
TEXT_PRIMARY = "#1a1a2e"      # Main text — dark charcoal
TEXT_SECONDARY = "#5a5a70"    # Secondary text
TEXT_TERTIARY = "#8888a0"     # Muted/placeholder text
TEXT_INVERSE = "#ffffff"       # Text on dark backgrounds

# Accent — Red
ACCENT_PRIMARY = "#c41e3a"    # Deep red — primary accent
ACCENT_LIGHT = "#e8364f"      # Lighter red — hover
ACCENT_DARK = "#9a1830"       # Darker red — pressed
ACCENT_BG = "#fdf0f2"         # Very light red background
ACCENT_SUBTLE = "#fce8ec"     # Subtle red tint

# Status colors
STATUS_OK = "#2d8a4e"         # Green — working/detected
STATUS_WARN = "#d4870e"       # Orange — warning
STATUS_ERROR = "#c41e3a"      # Red — error/not detected
STATUS_INFO = "#3a6bc4"       # Blue — info
STATUS_MUTED = "#8888a0"      # Gray — unavailable

# GPU-specific
GPU_DISCRETE = "#2d8a4e"      # Green — discrete GPU active
GPU_INTEGRATED = "#d4870e"    # Orange — integrated GPU

# Telemetry colors (for metric values)
METRIC_LOW = "#2d8a4e"        # Green — low utilization (good)
METRIC_MED = "#d4870e"        # Orange — medium utilization
METRIC_HIGH = "#c41e3a"       # Red — high utilization (warning)


def metric_color(value: float, low_threshold: float = 70, high_threshold: float = 90) -> str:
    """Return color based on utilization/temperature thresholds."""
    if value < low_threshold:
        return METRIC_LOW
    elif value < high_threshold:
        return METRIC_MED
    return METRIC_HIGH


def temp_color(temp: float) -> str:
    """Return color for temperature values."""
    if temp is None or temp <= 0:
        return STATUS_MUTED
    if temp < 70:
        return METRIC_LOW
    elif temp < 80:
        return METRIC_MED
    return METRIC_HIGH


# ============================================================
# TYPOGRAPHY
# ============================================================

FONT_FAMILY = "'Inter', 'Segoe UI', 'SF Pro Display', sans-serif"
FONT_MONO = "'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace"

# Font sizes
FONT_SIZE_XL = "22px"     # Large metric values
FONT_SIZE_LG = "16px"     # Section titles
FONT_SIZE_MD = "13px"     # Body text, labels
FONT_SIZE_SM = "11px"     # Small labels, captions
FONT_SIZE_XS = "9px"      # Tiny labels, status text

# Font weights
WEIGHT_BOLD = "700"
WEIGHT_SEMIBOLD = "600"
WEIGHT_MEDIUM = "500"
WEIGHT_REGULAR = "400"

# ============================================================
# SPACING & SIZING
# ============================================================

RADIUS_SM = "4px"
RADIUS_MD = "6px"
RADIUS_LG = "8px"
RADIUS_XL = "12px"

SPACING_XS = "2px"
SPACING_SM = "4px"
SPACING_MD = "8px"
SPACING_LG = "12px"
SPACING_XL = "16px"

# ============================================================
# STYLE SHEETS
# ============================================================


def global_stylesheet() -> str:
    """Return the complete global stylesheet for Heaven Society."""
    return f"""
        /* ===== Global ===== */
        QMainWindow {{
            background-color: {BG_PRIMARY};
        }}
        QWidget#centralWidget {{
            background-color: {BG_PRIMARY};
        }}
        QWidget {{
            background-color: transparent;
            color: {TEXT_PRIMARY};
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_MD};
        }}

        /* ===== Scroll Bars ===== */
        QScrollArea {{
            border: none;
            background-color: transparent;
        }}
        QScrollBar:vertical {{
            background-color: {BG_PRIMARY};
            width: 5px;
            border-radius: 2px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {BORDER_MEDIUM};
            border-radius: 2px;
            min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar:horizontal {{
            background-color: {BG_PRIMARY};
            height: 5px;
            border-radius: 2px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {BORDER_MEDIUM};
            border-radius: 2px;
            min-width: 20px;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0;
        }}

        /* ===== Combo Box ===== */
        QComboBox {{
            background-color: {BG_PANEL};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_LIGHT};
            border-radius: {RADIUS_SM};
            padding: 5px 10px;
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_MEDIUM};
        }}
        QComboBox:hover {{
            border-color: {BORDER_MEDIUM};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {BG_PANEL};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_LIGHT};
            border-radius: {RADIUS_SM};
            selection-background-color: {ACCENT_SUBTLE};
            selection-color: {ACCENT_PRIMARY};
        }}

        /* ===== Spin Box ===== */
        QSpinBox {{
            background-color: {BG_PANEL};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_LIGHT};
            border-radius: {RADIUS_SM};
            padding: 4px;
            font-size: {FONT_SIZE_SM};
        }}
        QSpinBox:hover {{
            border-color: {BORDER_MEDIUM};
        }}

        /* ===== Progress Bar ===== */
        QProgressBar {{
            background-color: {BG_INPUT};
            border-radius: 2px;
            border: none;
        }}
        QProgressBar::chunk {{
            background-color: {ACCENT_PRIMARY};
            border-radius: 2px;
        }}

        /* ===== Text Edit ===== */
        QTextEdit {{
            background-color: {BG_PANEL};
            color: {TEXT_SECONDARY};
            border: 1px solid {BORDER_LIGHT};
            border-radius: {RADIUS_SM};
            font-family: {FONT_MONO};
            font-size: {FONT_SIZE_SM};
            padding: 6px;
        }}
        QTextEdit:focus {{
            border-color: {BORDER_FOCUS};
        }}

        /* ===== Table ===== */
        QTableWidget {{
            background-color: {BG_PANEL};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_LIGHT};
            border-radius: {RADIUS_MD};
            font-size: {FONT_SIZE_SM};
            gridline-color: {BORDER_LIGHT};
        }}
        QTableWidget::item {{
            padding: 4px 8px;
        }}
        QTableWidget::item:selected {{
            background-color: {ACCENT_SUBTLE};
            color: {ACCENT_PRIMARY};
        }}
        QHeaderView::section {{
            background-color: {BG_INPUT};
            color: {TEXT_SECONDARY};
            border: none;
            border-bottom: 1px solid {BORDER_LIGHT};
            padding: 6px 8px;
            font-size: {FONT_SIZE_XS};
            font-weight: {WEIGHT_SEMIBOLD};
            text-transform: uppercase;
        }}
    """


def card_style(bg: str = BG_PANEL, border: str = BORDER_LIGHT, radius: str = RADIUS_MD) -> str:
    """Return a card/panel style string."""
    return f"""
        background-color: {bg};
        border: 1px solid {border};
        border-radius: {radius};
    """


def button_primary_style() -> str:
    """Return primary action button style (red accent)."""
    return f"""
        QPushButton {{
            background-color: {ACCENT_PRIMARY};
            color: {TEXT_INVERSE};
            border: none;
            border-radius: {RADIUS_MD};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_BOLD};
            padding: 8px 20px;
            letter-spacing: 0.5px;
        }}
        QPushButton:hover {{
            background-color: {ACCENT_LIGHT};
        }}
        QPushButton:pressed {{
            background-color: {ACCENT_DARK};
        }}
        QPushButton:disabled {{
            background-color: {BORDER_LIGHT};
            color: {TEXT_TERTIARY};
        }}
    """


def button_secondary_style() -> str:
    """Return secondary/outline button style."""
    return f"""
        QPushButton {{
            background-color: {BG_PANEL};
            color: {TEXT_SECONDARY};
            border: 1px solid {BORDER_LIGHT};
            border-radius: {RADIUS_MD};
            font-size: {FONT_SIZE_SM};
            font-weight: {WEIGHT_SEMIBOLD};
            padding: 8px 16px;
        }}
        QPushButton:hover {{
            background-color: {BG_INPUT};
            border-color: {BORDER_MEDIUM};
            color: {TEXT_PRIMARY};
        }}
        QPushButton:pressed {{
            background-color: {BORDER_LIGHT};
        }}
    """


def status_dot(color: str) -> str:
    """Return a styled status dot indicator."""
    return f'<span style="color:{color}; font-size:8px;">●</span>'


def status_badge(text: str, color: str) -> str:
    """Return HTML for a small status badge."""
    return (
        f'<span style="'
        f'background-color:{color}15; '
        f'color:{color}; '
        f'font-size:9px; '
        f'font-weight:600; '
        f'padding:2px 6px; '
        f'border-radius:3px;'
        f'">{text}</span>'
    )


# ============================================================
# REUSABLE COMPONENT STYLES
# ============================================================


def section_header_style() -> str:
    """Style for section header labels (e.g. TARGET, PERFORMANCE)."""
    return f"""
        color: {TEXT_TERTIARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_XS};
        font-weight: {WEIGHT_BOLD};
        letter-spacing: 2px;
        border: none;
    """


def card_title_style() -> str:
    """Style for card/panel title labels."""
    return f"""
        color: {TEXT_TERTIARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_XS};
        font-weight: {WEIGHT_BOLD};
        letter-spacing: 1px;
        border: none;
    """


def metric_title_style() -> str:
    """Style for metric block title labels (CPU, GPU, etc)."""
    return f"""
        color: {TEXT_TERTIARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_XS};
        font-weight: {WEIGHT_SEMIBOLD};
        letter-spacing: 1px;
        border: none;
    """


def metric_value_style(color: str = TEXT_PRIMARY) -> str:
    """Style for metric block value labels."""
    return f"""
        color: {color};
        font-family: {FONT_MONO};
        font-size: {FONT_SIZE_LG};
        font-weight: {WEIGHT_BOLD};
        border: none;
    """


def metric_value_sm_style(color: str = TEXT_PRIMARY) -> str:
    """Style for small metric value labels."""
    return f"""
        color: {color};
        font-family: {FONT_MONO};
        font-size: {FONT_SIZE_SM};
        font-weight: {WEIGHT_BOLD};
        border: none;
    """


def unit_label_style() -> str:
    """Style for unit labels (%, ms, etc)."""
    return f"""
        color: {TEXT_TERTIARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_XS};
        border: none;
    """


def body_text_style(color: str = TEXT_SECONDARY) -> str:
    """Style for body text labels."""
    return f"""
        color: {color};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_SM};
        border: none;
    """


def mono_text_style(color: str = TEXT_SECONDARY) -> str:
    """Style for monospace text labels."""
    return f"""
        color: {color};
        font-family: {FONT_MONO};
        font-size: {FONT_SIZE_XS};
        border: none;
    """


def status_indicator_style(color: str = TEXT_TERTIARY) -> str:
    """Style for status indicator labels (score, confidence, etc)."""
    return f"""
        color: {color};
        font-family: {FONT_MONO};
        font-size: {FONT_SIZE_XS};
        font-weight: {WEIGHT_BOLD};
        border: none;
    """


def opt_row_style() -> str:
    """Style for optimization status rows."""
    return f"""
        background-color: {BG_PANEL};
        border: 1px solid {BORDER_LIGHT};
        border-radius: {RADIUS_MD};
    """


def opt_row_name_style() -> str:
    """Style for optimization row name labels."""
    return f"""
        color: {TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_SM};
        font-weight: {WEIGHT_MEDIUM};
        border: none;
    """


def opt_row_value_style() -> str:
    """Style for optimization row value labels."""
    return f"""
        color: {TEXT_SECONDARY};
        font-family: {FONT_MONO};
        font-size: {FONT_SIZE_XS};
        border: none;
    """


def opt_row_status_style(color: str = TEXT_TERTIARY) -> str:
    """Style for optimization row status badges."""
    return f"""
        color: {color};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_XS};
        font-weight: {WEIGHT_SEMIBOLD};
        background-color: {color}15;
        border-radius: 3px;
        padding: 2px 4px;
        border: none;
    """


def loading_placeholder_style() -> str:
    """Style for loading placeholder text."""
    return f"""
        color: {TEXT_TERTIARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_XS};
        font-style: italic;
        border: none;
    """


def no_data_style() -> str:
    """Style for N/A / no-data labels."""
    return f"""
        color: {TEXT_TERTIARY};
        font-family: {FONT_MONO};
        font-size: {FONT_SIZE_SM};
        font-weight: {WEIGHT_MEDIUM};
        border: none;
    """


def tab_button_active_style() -> str:
    """Active tab button style for panel mode."""
    return f"""
        QPushButton {{
            background-color: {ACCENT_PRIMARY};
            color: #ffffff;
            border: none;
            border-radius: 4px;
            font-size: 14px;
            font-weight: {WEIGHT_BOLD};
            padding: 4px 6px;
        }}
    """


def tab_button_inactive_style() -> str:
    """Inactive tab button style for panel mode."""
    return f"""
        QPushButton {{
            background-color: transparent;
            color: {TEXT_TERTIARY};
            border: none;
            border-radius: 4px;
            font-size: 14px;
            padding: 4px 6px;
        }}
        QPushButton:hover {{
            background-color: {ACCENT_SUBTLE};
            color: {ACCENT_PRIMARY};
        }}
    """
