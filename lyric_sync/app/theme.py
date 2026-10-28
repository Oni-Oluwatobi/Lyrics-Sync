"""TKG visual identity: design tokens, palettes and the unified style sheet.

Brand constitution: Orange · Yellow · White · Deep Charcoal · Slate.
No blue, no cyan, no purple gradients — ever.

Two rules keep the app fast on low-end hardware:

* No ``font-family`` rule — a styled font family triggers a multi-second
  one-time Qt warm-up on Windows (measured 2.8-5.6 s).  The native stack
  (Segoe UI first) is applied once through ``QFont`` in ``application.py``.
* No per-widget graphic effects (shadows, blur) — flat surfaces, 1 px
  borders and colour shifts carry the whole hierarchy.

Spatial system: every gap is a multiple of the 8-point grid (4 px half-steps
allowed only for icon/label micro-alignment).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


# ---------------------------------------------------------- TKG colour tokens
# Core brand
TKG_ORANGE_PRIMARY = "#FF6A00"   # CTAs, primary active states, focus rings
TKG_ORANGE_HOVER = "#FF8533"     # primary hover
TKG_ORANGE_PRESSED = "#E05D00"   # micro-depression state
TKG_YELLOW_ACCENT = "#FFD400"    # highlights, badges, search hit spans
TKG_YELLOW_MUTED = "rgba(255, 212, 0, 0.18)"  # excerpt highlight background

# Dark canvas — neutral near-black (never pure #000000: avoids halation).
# Approved surface ladder: #0A0A0A (window) / #0D0D0D (chrome) /
# #111111–#171717 (panels) with #252525 borders. No blue tints, ever.
DARK_BG_BASE = "#0A0A0A"
DARK_BG_CHROME = "#0D0D0D"
DARK_BG_SURFACE = "#111111"
DARK_BG_ELEVATED = "#171717"
DARK_BG_INPUT = "#101010"
DARK_BORDER_SUBTLE = "#252525"
DARK_BORDER_STRONG = "#333333"
DARK_TEXT_PRIMARY = "#FFFFFF"
DARK_TEXT_SECONDARY = "#A8A8A8"
DARK_TEXT_MUTED = "#737373"

# Light canvas
LIGHT_BG_BASE = "#F9FAFB"
LIGHT_BG_SURFACE = "#FFFFFF"
LIGHT_BG_ELEVATED = "#F3F4F6"
LIGHT_BORDER_SUBTLE = "#E5E7EB"
LIGHT_BORDER_STRONG = "#D1D5DB"
LIGHT_TEXT_PRIMARY = "#111827"
LIGHT_TEXT_SECONDARY = "#4B5563"
LIGHT_TEXT_MUTED = "#9CA3AF"

# Semantic match-label badges (never blue)
MATCH_STRONG_BG = "rgba(255, 106, 0, 0.15)"
MATCH_STRONG_TEXT = "#FF8533"
MATCH_STRONG_BORDER = "rgba(255, 106, 0, 0.40)"

MATCH_GOOD_BG = "rgba(255, 212, 0, 0.12)"
MATCH_GOOD_TEXT = "#FFD400"
MATCH_GOOD_BORDER = "rgba(255, 212, 0, 0.35)"

MATCH_POSSIBLE_BG = "rgba(156, 163, 175, 0.10)"
MATCH_POSSIBLE_TEXT = "#9CA3AF"
MATCH_POSSIBLE_BORDER = "rgba(156, 163, 175, 0.25)"

# Nav rail active tints
NAV_ACTIVE_BG = "rgba(255, 106, 0, 0.12)"
NAV_ACTIVE_TEXT = TKG_ORANGE_HOVER
NAV_HOVER_BG = "rgba(255, 255, 255, 0.04)"

# Status semantics (health indicators only — not brand chrome)
OK_GREEN_DARK = "#22C55E"
OK_GREEN_LIGHT = "#16A34A"

# Card hover warm (result rows etc.)
CARD_HOVER_BORDER = "rgba(255, 106, 0, 0.30)"

# --------------------------------------------------------------- spatial grid
# 8-point grid: 8 / 16 / 24 / 32 / 40 / 48.  SP_XS is a half-step used only
# for icon-to-label micro alignment.
SP_XS = 4
SP_SM = 8
SP_MD = 16
SP_LG = 24
SP_XL = 32
SP_2XL = 40
SP_3XL = 48

# Corner radius scale (px).
R_XS = 4
R_SM = 6
R_MD = 8
R_LG = 12
R_PILL = 14
R_XL = 16

# Content column: shared width envelope for every page.
PAGE_MIN_WIDTH = 520
PAGE_MAX_WIDTH = 920
PAGE_WIDTH_RATIO = 0.88

# Fixed chrome sizes.
NAV_RAIL_WIDTH = 200
NAV_ITEM_HEIGHT = 40
HEADER_HEIGHT = 52


@dataclass(frozen=True)
class Palette:
    name: str
    mode: str

    window: str
    chrome: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str

    text: str
    text_muted: str
    text_dim: str

    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    yellow: str
    yellow_soft: str
    on_accent: str
    danger: str

    input: str
    ok: str

    match_strong_bg: str
    match_strong_text: str
    match_strong_border: str
    match_good_bg: str
    match_good_text: str
    match_good_border: str
    match_possible_bg: str
    match_possible_text: str
    match_possible_border: str

    shadow: str


DARK = Palette(
    name="TKG Dark",
    mode="dark",
    window=DARK_BG_BASE,
    chrome=DARK_BG_CHROME,
    surface=DARK_BG_SURFACE,
    surface_alt=DARK_BG_ELEVATED,
    surface_hover=DARK_BG_ELEVATED,
    border=DARK_BORDER_SUBTLE,
    border_strong=DARK_BORDER_STRONG,
    text=DARK_TEXT_PRIMARY,
    text_muted=DARK_TEXT_SECONDARY,
    text_dim=DARK_TEXT_MUTED,
    accent=TKG_ORANGE_PRIMARY,
    accent_hover=TKG_ORANGE_HOVER,
    accent_pressed=TKG_ORANGE_PRESSED,
    accent_soft=NAV_ACTIVE_BG,
    yellow=TKG_YELLOW_ACCENT,
    yellow_soft=TKG_YELLOW_MUTED,
    on_accent="#FFFFFF",
    danger="#FF5F56",
    input=DARK_BG_INPUT,
    ok=OK_GREEN_DARK,
    match_strong_bg=MATCH_STRONG_BG,
    match_strong_text=MATCH_STRONG_TEXT,
    match_strong_border=MATCH_STRONG_BORDER,
    match_good_bg=MATCH_GOOD_BG,
    match_good_text=MATCH_GOOD_TEXT,
    match_good_border=MATCH_GOOD_BORDER,
    match_possible_bg=MATCH_POSSIBLE_BG,
    match_possible_text=MATCH_POSSIBLE_TEXT,
    match_possible_border=MATCH_POSSIBLE_BORDER,
    shadow="#000000",
)

LIGHT = Palette(
    name="TKG Light",
    mode="light",
    window=LIGHT_BG_BASE,
    chrome=LIGHT_BG_ELEVATED,
    surface=LIGHT_BG_SURFACE,
    surface_alt=LIGHT_BG_ELEVATED,
    surface_hover=LIGHT_BG_ELEVATED,
    border=LIGHT_BORDER_SUBTLE,
    border_strong=LIGHT_BORDER_STRONG,
    text=LIGHT_TEXT_PRIMARY,
    text_muted=LIGHT_TEXT_SECONDARY,
    text_dim=LIGHT_TEXT_MUTED,
    accent=TKG_ORANGE_PRIMARY,
    accent_hover=TKG_ORANGE_HOVER,
    accent_pressed=TKG_ORANGE_PRESSED,
    accent_soft="rgba(255, 106, 0, 0.12)",
    yellow=TKG_YELLOW_ACCENT,
    yellow_soft="rgba(255, 212, 0, 0.18)",
    on_accent="#FFFFFF",
    danger="#D93B32",
    input=LIGHT_BG_SURFACE,
    ok=OK_GREEN_LIGHT,
    # On the light canvas the raw badge colours lose contrast, so text roles
    # resolve to darkened shades of the same hue (still never blue).
    match_strong_bg="rgba(255, 106, 0, 0.10)",
    match_strong_text="#C2410C",
    match_strong_border="rgba(255, 106, 0, 0.35)",
    match_good_bg="rgba(255, 212, 0, 0.18)",
    match_good_text="#854D0E",
    match_good_border="rgba(255, 212, 0, 0.50)",
    match_possible_bg="rgba(156, 163, 175, 0.14)",
    match_possible_text="#4B5563",
    match_possible_border="rgba(156, 163, 175, 0.35)",
    shadow="#111827",
)

PALETTES = {"dark": DARK, "light": LIGHT}
SYSTEM_MODES = ("system", "light", "dark")


def system_is_dark() -> bool:
    """Best-effort detection of the operating system colour scheme."""
    app = QApplication.instance()
    if app is not None:
        window = app.palette().color(QPalette.Window)
        return window.lightness() < 128
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
        except OSError:
            return True
    if sys.platform == "darwin":
        # Headless (pre-QApplication) detection on macOS. The preference key
        # only exists while dark mode is active; light is the system default.
        try:
            import subprocess

            completed = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return completed.returncode == 0 and "Dark" in completed.stdout
        except (OSError, subprocess.SubprocessError):
            return False
    return True


def resolve_palette(mode: str) -> Palette:
    if mode == "system":
        return DARK if system_is_dark() else LIGHT
    return LIGHT if mode == "light" else DARK


def build_stylesheet(p: Palette) -> str:
    """Full application style sheet for the given palette.

    Every interactive widget implements the state matrix:
    Default · Hover · Active (pressed) · Focus · Disabled · Loading ·
    Error · Empty — through ``:hover``, ``:pressed``, ``:focus``,
    ``:disabled`` and explicit ``[state=...]`` / ``[loading=...]``
    properties the pages set at runtime.
    """
    return f"""
/* ==================================================================== base */
QWidget {{
    font-size: 14px;
    color: {p.text};
    background: transparent;
}}
QMainWindow, #appRoot {{
    background: {p.window};
}}
#appHeader {{
    background: {p.chrome};
    border-bottom: 1px solid {p.border};
}}
QToolTip {{
    background: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {R_XS}px;
    padding: 6px 10px;
    font-size: 12px;
}}
QToolTip[state="error"] {{
    background: {p.danger};
    color: #FFFFFF;
    border-color: {p.danger};
}}

/* ============================================================== typography */
QLabel[role="brand"] {{ font-size: 16px; font-weight: 700; letter-spacing: 0.2px; }}
QLabel[role="brandSub"] {{ font-size: 11px; color: {p.text_muted}; letter-spacing: 0.4px; font-weight: 400; }}
QLabel[role="tagline"] {{ font-size: 12px; color: {p.text_muted}; letter-spacing: 0.3px; }}
QLabel[role="display"] {{ font-size: 24px; font-weight: 600; color: {p.text}; letter-spacing: -0.2px; }}
QLabel[role="pageTitle"] {{ font-size: 20px; font-weight: 600; color: {p.text}; }}
QLabel[role="heading"] {{ font-size: 17px; font-weight: 600; }}
QLabel[role="title"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="fieldTitle"] {{ font-size: 14px; font-weight: 600; color: {p.text}; }}
QLabel[role="byline"] {{ font-size: 15px; font-weight: 400; color: {p.text_muted}; }}
QLabel[role="body"] {{ font-size: 14px; color: {p.text_muted}; }}
QLabel[role="muted"] {{ font-size: 13px; color: {p.text_muted}; }}
QLabel[role="caption"] {{ font-size: 11px; font-weight: 600; color: {p.text_dim}; letter-spacing: 0.5px; }}
QLabel[role="accent"] {{ color: {p.accent}; }}
QLabel[role="snippet"] {{ font-size: 14px; color: {p.text_muted}; }}
QLabel[role="section"] {{
    font-size: 15px;
    font-weight: 500;
    letter-spacing: 0.5px;
    color: {p.text_muted};
}}
QLabel[role="lyric"] {{ font-size: 15px; color: {p.text}; }}
QLabel[role="emptyTitle"] {{ font-size: 17px; font-weight: 600; }}
QLabel[role="emptyBody"] {{ font-size: 14px; color: {p.text_muted}; }}
QLabel[role="metricValue"] {{ font-size: 20px; font-weight: 600; color: {p.text}; }}
QLabel[role="metricLabel"] {{ font-size: 11px; font-weight: 600; letter-spacing: 0.5px; color: {p.text_dim}; }}
QLabel[state="error"] {{ color: {p.danger}; }}
QLabel[role="mono"] {{
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
    color: {p.text_muted};
}}

/* =============================================================== nav rail */
#navRail {{
    background: {p.chrome};
    border-right: 1px solid {p.border};
}}
QPushButton[variant="rail"] {{
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: {R_SM}px;
    padding: 8px 12px;
    margin: 0px 12px;
    font-size: 14px;
    font-weight: 500;
    color: {p.text_muted};
    text-align: left;
}}
QPushButton[variant="rail"]:hover {{ background: {"rgba(255, 255, 255, 0.04)" if p.mode == "dark" else "rgba(0, 0, 0, 0.04)"}; color: {p.text}; }}
QPushButton[variant="rail"]:pressed {{ background: {p.surface_alt}; }}
QPushButton[variant="rail"]:focus {{ border: 1px solid {p.accent}; border-left: 3px solid {p.accent}; }}
QPushButton[variant="rail"]:disabled {{ color: {p.text_dim}; }}
QPushButton[variant="rail"]:checked {{
    background: {p.accent_soft};
    color: {p.accent_hover if p.mode == "dark" else p.accent_pressed};
    border-left: 3px solid {p.accent};
}}
#railFooter {{
    background: {p.chrome};
    border-top: 1px solid {p.border};
}}
#statusDot {{
    background: {p.accent};
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}}
#statusDot[state="ok"] {{ background: {p.ok}; }}
#statusDot[state="missing"] {{ background: {p.text_dim}; }}
#statusDot[state="error"] {{ background: {p.danger}; }}

/* ================================================================ buttons */
QPushButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {R_SM}px;
    padding: 8px 16px;
    font-size: 14px;
    font-weight: 500;
    color: {p.text};
}}
QPushButton:hover {{ background: {p.surface_hover}; }}
QPushButton:pressed {{ background: {p.surface_alt}; }}
QPushButton:focus {{ border: 1px solid {p.accent}; }}
QPushButton:disabled {{ color: {p.text_dim}; background: transparent; border-color: transparent; }}

QPushButton[variant="primary"] {{
    background: {p.accent};
    color: {p.on_accent};
    border: 1px solid {p.accent};
    border-radius: {R_SM}px;
    font-weight: 600;
    padding: 9px 20px;
}}
QPushButton[variant="primary"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {p.accent_pressed}; border-color: {p.accent_pressed}; }}
QPushButton[variant="primary"]:focus {{ border: 2px solid {p.accent_hover}; }}
QPushButton[variant="primary"]:disabled {{
    background: {p.surface_alt};
    border-color: {p.border};
    color: {p.text_dim};
}}

QPushButton[variant="secondary"] {{
    background: {p.surface};
    border: 1px solid {p.border_strong};
    border-radius: {R_SM}px;
    padding: 8px 16px;
}}
QPushButton[variant="secondary"]:hover {{ background: {p.surface_hover}; border-color: {p.accent}; }}
QPushButton[variant="secondary"]:pressed {{ background: {p.surface_alt}; border-color: {p.accent_pressed}; }}
QPushButton[variant="secondary"]:disabled {{ border-color: {p.border}; color: {p.text_dim}; }}

QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {p.text_muted};
    padding: 7px 12px;
}}
QPushButton[variant="ghost"]:hover {{ background: {p.surface_hover}; color: {p.text}; }}
QPushButton[variant="ghost"]:pressed {{ background: {p.surface_alt}; }}
QPushButton[variant="ghost"]:disabled {{ color: {p.text_dim}; }}

QPushButton[variant="danger"] {{
    background: transparent;
    border: 1px solid {p.border};
    color: {p.danger};
    padding: 8px 16px;
}}
QPushButton[variant="danger"]:hover {{ border-color: {p.danger}; background: {p.surface_hover}; }}
QPushButton[variant="danger"]:pressed {{ background: {p.surface_alt}; }}

QPushButton[variant="icon"] {{
    padding: 6px;
    border-radius: {R_SM}px;
    min-width: 30px;
    min-height: 30px;
}}

QPushButton[variant="toggle"] {{
    background: transparent;
    border: 1px solid {p.border};
    color: {p.text_muted};
    padding: 6px 14px;
    font-size: 13px;
}}
QPushButton[variant="toggle"]:hover {{ border-color: {p.border_strong}; color: {p.text}; }}
QPushButton[variant="toggle"]:checked {{
    background: {p.accent_soft};
    border: 1px solid {p.accent};
    color: {p.accent};
    font-weight: 600;
}}

QPushButton[loading="true"] {{
    color: {p.text_dim};
    background: {p.surface_alt};
}}

/* =============================================================== segmented */
#segmented {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {R_SM}px;
    padding: 3px;
}}
#segmented QPushButton {{
    border-radius: {R_XS}px;
    padding: 6px 14px;
    color: {p.text_muted};
    font-weight: 500;
    font-size: 13px;
    border: 1px solid transparent;
}}
#segmented QPushButton:hover {{ color: {p.text}; background: {"rgba(255, 255, 255, 0.05)" if p.mode == "dark" else "rgba(0, 0, 0, 0.04)"}; }}
#segmented QPushButton:checked {{
    background: {p.surface};
    color: {p.accent};
    border: 1px solid {p.border_strong};
    font-weight: 600;
}}
#segmented QPushButton:disabled {{ color: {p.text_dim}; }}

/* ================================================================= inputs */
QLineEdit, QPlainTextEdit {{
    background: {p.input};
    border: 1px solid {p.border};
    border-radius: {R_SM}px;
    padding: 8px 12px;
    font-size: 14px;
    color: {p.text};
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QLineEdit:hover, QPlainTextEdit:hover {{ border-color: {p.border_strong}; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {p.accent}; }}
QLineEdit:disabled, QPlainTextEdit:disabled {{ color: {p.text_dim}; background: {p.surface_alt}; }}
QLineEdit[state="error"] {{ border: 1px solid {p.danger}; }}
QLineEdit[readOnly="true"] {{ color: {p.text_muted}; }}

QComboBox {{
    background: {p.input};
    border: 1px solid {p.border};
    border-radius: {R_SM}px;
    padding: 8px 12px;
    font-size: 14px;
    color: {p.text};
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QComboBox:hover {{ border-color: {p.border_strong}; }}
QComboBox:focus {{ border: 1px solid {p.accent}; }}
QComboBox:disabled {{ color: {p.text_dim}; background: {p.surface_alt}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p.text_muted};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {p.surface_alt};
    border: 1px solid {p.border_strong};
    border-radius: {R_SM}px;
    padding: 4px;
    selection-background-color: {p.accent_soft};
    selection-color: {p.text};
    outline: none;
}}

QCheckBox {{ spacing: 9px; font-size: 14px; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {p.border_strong};
    border-radius: {R_XS}px;
    background: {p.input};
}}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
}}
QCheckBox::indicator:disabled {{ background: {p.surface_alt}; border-color: {p.border}; }}
QCheckBox:disabled {{ color: {p.text_dim}; }}

QRadioButton {{ spacing: 9px; font-size: 14px; }}
QRadioButton::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {p.border_strong};
    border-radius: 9px;
    background: {p.input};
}}
QRadioButton::indicator:hover {{ border-color: {p.accent}; }}
QRadioButton::indicator:checked {{
    border: 1px solid {p.accent};
    background: {p.input};
}}
QRadioButton:disabled {{ color: {p.text_dim}; }}

/* ================================================================= panels */
#panel {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {R_MD}px;
}}
#panelFlat {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {R_MD}px;
}}
#notice {{
    background: {p.yellow_soft};
    border: 1px solid {p.yellow};
    border-radius: {R_MD}px;
}}
#notice QLabel {{ color: {p.text}; }}
#banner {{
    background: {p.match_strong_bg};
    border: 1px solid {p.match_strong_border};
    border-radius: {R_MD}px;
}}
#divider {{ background: {p.border}; max-height: 1px; }}
#inspector {{
    background: {p.surface};
    border-left: 1px solid {p.border};
}}

/* ================================================== cards (result / grid) */
#listRow {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {R_MD}px;
}}
#listRow[hover="true"] {{
    border-color: {CARD_HOVER_BORDER};
    background: {p.surface_alt};
}}
#listRow[selected="true"] {{
    border: 1px solid {p.accent};
    background: {p.accent_soft};
}}
#listRow[pressable="true"] {{ cursor: pointer; }}
#listRow[pressable="true"]:disabled {{ opacity: 0.6; }}
#rowChevron {{ color: {p.text_dim}; background: transparent; }}
#listRow[selected="true"] #rowChevron {{ color: {p.accent}; }}
#starButton {{
    background: transparent;
    border: none;
    border-radius: {R_SM}px;
    padding: 4px;
}}
#starButton:hover {{ background: {p.surface_hover}; }}

/* ================================================================== chips */
QLabel[kind="strong"] {{
    background: {p.match_strong_bg};
    color: {p.match_strong_text};
    border: 1px solid {p.match_strong_border};
    border-radius: {R_PILL}px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QLabel[kind="good"] {{
    background: {p.match_good_bg};
    color: {p.match_good_text};
    border: 1px solid {p.match_good_border};
    border-radius: {R_PILL}px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QLabel[kind="possible"] {{
    background: {p.match_possible_bg};
    color: {p.match_possible_text};
    border: 1px solid {p.match_possible_border};
    border-radius: {R_PILL}px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QLabel[kind="verified"] {{
    background: {p.accent_soft};
    color: {p.accent};
    border: 1px solid {p.accent};
    border-radius: {R_PILL}px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QLabel[kind="meta"] {{
    background: {p.surface_alt};
    color: {p.text_muted};
    border: 1px solid {p.border};
    border-radius: {R_PILL}px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QLabel[kind="warn"] {{
    background: {p.yellow_soft};
    color: {p.text};
    border: 1px solid {p.yellow};
    border-radius: {R_PILL}px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel[kind="pill"] {{
    background: {p.surface_alt};
    color: {p.text_muted};
    border: 1px solid {p.border};
    border-radius: {R_PILL}px;
    padding: 5px 14px;
    font-size: 13px;
    font-weight: 500;
}}
QLabel[kind="pill"]:hover {{ border-color: {p.accent}; color: {p.text}; }}
QLabel[kind="pill"][hover="true"] {{ background: {p.surface_hover}; border-color: {p.accent}; color: {p.text}; }}

/* =============================================================== sections */
#sectionPill {{
    background: {p.accent_soft};
    color: {p.accent};
    border-radius: {R_PILL}px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
#repeatBadge {{
    background: {p.surface_alt};
    color: {p.text_dim};
    border: 1px solid {p.border};
    border-radius: {R_XS}px;
    padding: 1px 5px;
    font-size: 10px;
    font-weight: 600;
}}

/* ============================================================= list rows */
QListWidget, QTreeWidget, QTableWidget {{
    background: transparent;
    border: none;
    outline: none;
    font-size: 14px;
}}
QListWidget::item {{
    border: none;
    border-radius: {R_MD}px;
    padding: 0px;
    margin-bottom: {SP_SM}px;
}}
QListWidget::item:selected {{ background: transparent; color: {p.text}; }}
QTreeWidget, QTableWidget {{
    border: 1px solid {p.border};
    border-radius: {R_MD}px;
    background: {p.surface};
    alternate-background-color: {p.surface_alt};
}}
QTreeWidget::item {{ padding: 5px 6px; border: none; }}
QTreeWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QTableWidget {{ gridline-color: {p.border}; }}
QTableWidget::item {{ padding: 4px 8px; }}
QTableWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QHeaderView::section {{
    background: {p.surface_alt};
    color: {p.text_muted};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}

/* =============================================================== scrolling */
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {p.border_strong};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.accent}; }}
QScrollBar::handle:vertical:disabled {{ background: {p.border}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; background: transparent; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 4px; min-width: 32px; }}
QScrollBar::handle:horizontal:hover {{ background: {p.accent}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; background: transparent; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* =============================================================== progress */
QProgressBar {{
    background: transparent;
    border: none;
    max-height: 2px;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 1px; }}

/* ============================================================ search box */
#searchShell {{
    background: {p.input};
    border: 2px solid {p.border_strong};
    border-radius: {R_PILL}px;
}}
#searchShell[active="true"] {{ border: 2px solid {p.accent}; }}
#searchShell:hover {{ border-color: {p.accent}; }}
#searchShell[loading="true"] {{ border-color: {p.accent}; }}
#searchShellCompact {{
    background: {p.input};
    border: 2px solid {p.border};
    border-radius: {R_LG}px;
}}
#searchShellCompact[active="true"] {{ border: 2px solid {p.accent}; }}
#searchShellCompact:hover {{ border-color: {p.border_strong}; }}
#searchShellCompact[loading="true"] {{ border-color: {p.accent}; }}
QLineEdit#searchInput {{
    background: transparent;
    border: none;
    padding: 0;
    font-size: 15px;
    font-weight: 400;
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QLineEdit#searchInput:focus {{ border: none; }}
QLineEdit#searchInputCompact {{
    background: transparent;
    border: none;
    padding: 0;
    font-size: 14px;
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QLineEdit#searchInput:disabled, QLineEdit#searchInputCompact:disabled {{ color: {p.text_dim}; }}
#keyHint {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {R_XS}px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
    color: {p.text_dim};
}}
#searchClear {{
    background: transparent;
    border: none;
    border-radius: {R_SM}px;
    color: {p.text_muted};
    padding: 0;
}}
#searchClear:hover {{ background: {p.surface_hover}; color: {p.text}; }}

/* ================================================================== misc */
#recentRow {{
    background: transparent;
    border: 1px solid {p.border};
    border-radius: {R_PILL}px;
}}
#recentRow[hover="true"] {{ border-color: {p.accent}; background: {p.surface}; }}

#metaKey {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
    color: {p.text_dim};
}}
#metaValue {{ font-size: 13px; color: {p.text}; }}

/* Skeleton / loading placeholders (#skeleton blocks painted by widgets). */
#skeleton {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {R_MD}px;
}}

/* ================================================================== menus */
QMenu {{
    background: {p.surface_alt};
    border: 1px solid {p.border_strong};
    border-radius: {R_SM}px;
    padding: 4px;
}}
QMenu::item {{
    background: transparent;
    border-radius: {R_XS}px;
    padding: 6px 24px 6px 12px;
    color: {p.text};
}}
QMenu::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QMenu::item:disabled {{ color: {p.text_dim}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 8px; }}

QMessageBox {{
    background: {p.surface};
}}
"""


def apply_theme(app: QApplication, mode: str) -> Palette:
    """Apply the requested theme (``light`` / ``dark`` / ``system``).

    The Fusion base style is installed once; re-running ``setStyle`` on every
    toggle would rebuild the style and re-polish the whole tree a second time.
    """
    palette = resolve_palette(mode)
    if not app.property("_tkgFusion"):
        app.setStyle("Fusion")
        app.setProperty("_tkgFusion", True)
    app.setStyleSheet(build_stylesheet(palette))

    qp = QPalette()
    qp.setColor(QPalette.Window, QColor(palette.window))
    qp.setColor(QPalette.WindowText, QColor(palette.text))
    qp.setColor(QPalette.Base, QColor(palette.surface))
    qp.setColor(QPalette.AlternateBase, QColor(palette.surface_alt))
    qp.setColor(QPalette.Text, QColor(palette.text))
    qp.setColor(QPalette.Button, QColor(palette.surface))
    qp.setColor(QPalette.ButtonText, QColor(palette.text))
    qp.setColor(QPalette.Highlight, QColor(palette.accent))
    qp.setColor(QPalette.HighlightedText, QColor(palette.on_accent))
    qp.setColor(QPalette.ToolTipBase, QColor(palette.surface_alt))
    qp.setColor(QPalette.ToolTipText, QColor(palette.text))
    qp.setColor(QPalette.PlaceholderText, QColor(palette.text_dim))
    qp.setColor(QPalette.Disabled, QPalette.Text, QColor(palette.text_dim))
    qp.setColor(QPalette.Disabled, QPalette.WindowText, QColor(palette.text_dim))
    app.setPalette(qp)
    app.setProperty("tkgMode", palette.mode)
    return palette
