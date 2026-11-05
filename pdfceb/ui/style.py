"""Thème visuel de PDF Ceb."""

ACCENT = "#4263eb"
ACCENT_DARK = "#364fc7"
ACCENT_SOFT = "#edf2ff"
BG = "#f4f6fa"
SURFACE = "#ffffff"
BORDER = "#e1e5ee"
TEXT = "#1f2430"
MUTED = "#6b7280"
DANGER = "#e03131"
SUCCESS = "#2f9e44"

CATEGORIES = {
    "organiser": ("Organiser", "#e8590c"),
    "optimiser": ("Optimiser", "#2f9e44"),
    "convertir": ("Convertir", "#1c7ed6"),
    "modifier": ("Modifier", "#7048e8"),
    "securite": ("Sécurité", "#c2255c"),
}

def soft(color: str, alpha: float = 0.12) -> str:
    """Couleur transparente au format rgba() (Qt lit #RRGGBBAA comme #AARRGGBB)."""
    c = color.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return f"rgba({r}, {g}, {b}, {int(alpha * 255)})"


def build_qss() -> str:
    """Feuille de style complète, avec les flèches des listes et compteurs."""
    import tempfile
    from pathlib import Path

    from . import icons
    d = Path(tempfile.gettempdir()) / "pdfceb_assets"
    d.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in ("chev_up", "chev_down"):
        f = d / f"{name}.png"
        icons.pixmap(name, "#4b5263", 16, 2.0, 2.4).save(str(f))
        paths[name] = f.as_posix()
    extra = f"""
QSpinBox, QDoubleSpinBox {{ padding-right: 24px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none;
    border-left: 1px solid {BORDER}; border-top-right-radius: 7px; background: #f7f8fb; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none;
    border-left: 1px solid {BORDER}; border-bottom-right-radius: 7px; background: #f7f8fb; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {ACCENT_SOFT}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{paths['chev_up']}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{paths['chev_down']}"); width: 10px; height: 10px; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 26px; border: none; }}
QComboBox::down-arrow {{ image: url("{paths['chev_down']}"); width: 12px; height: 12px; }}
"""
    return QSS + extra


QSS = f"""
* {{ color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#page {{ background: {BG}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QFrame#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QLabel#brand {{ font-size: 17px; font-weight: 700; }}
QLabel#brandSub {{ color: {MUTED}; font-size: 11px; }}
QLabel#sideSection {{ color: {MUTED}; font-size: 11px; font-weight: 600; padding: 9px 10px 3px 12px; }}
QPushButton#sideButton {{
    text-align: left; padding: 5px 10px; border: none; border-radius: 8px; background: transparent;
    font-size: 13px;
}}
QPushButton#sideButton:hover {{ background: #f1f3f8; }}
QPushButton#sideButton:checked {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; font-weight: 600; }}

QLabel#h1 {{ font-size: 24px; font-weight: 700; }}
QLabel#h2 {{ font-size: 15px; font-weight: 700; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#section {{ font-size: 13px; font-weight: 700; color: {TEXT}; padding-top: 6px; }}
QLabel#hint {{ color: {MUTED}; font-size: 12px; }}
QLabel#error {{ color: {DANGER}; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#card:hover {{ border: 1px solid {ACCENT}; background: #fbfcff; }}
QFrame#panel {{ background: {SURFACE}; border-left: 1px solid {BORDER}; }}
QFrame#box {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#banner {{ background: #fff4e6; border: 1px solid #ffd8a8; border-radius: 8px; }}
QFrame#infoBanner {{ background: {ACCENT_SOFT}; border: 1px solid #c5d0fa; border-radius: 8px; }}
QFrame#dropzone {{ background: {SURFACE}; border: 2px dashed #c3cad9; border-radius: 16px; }}
QFrame#dropzone[hover="true"] {{ border-color: {ACCENT}; background: {ACCENT_SOFT}; }}

QPushButton {{
    background: {SURFACE}; border: 1px solid #ccd2de; border-radius: 8px; padding: 6px 14px; font-size: 13px;
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT_DARK}; }}
QPushButton:pressed {{ background: #eef1f7; }}
QPushButton:disabled {{ color: #a0a6b4; border-color: #e1e5ee; }}
QPushButton#primary {{
    background: {ACCENT}; color: white; border: none; border-radius: 10px; padding: 12px 22px;
    font-size: 15px; font-weight: 700;
}}
QPushButton#primary:hover {{ background: {ACCENT_DARK}; color: white; }}
QPushButton#primary:disabled {{ background: #b9c4f5; color: #f4f6fa; }}
QPushButton#big {{
    background: {ACCENT}; color: white; border: none; border-radius: 12px; padding: 14px 30px;
    font-size: 16px; font-weight: 700;
}}
QPushButton#big:hover {{ background: {ACCENT_DARK}; color: white; }}
QPushButton#danger {{ background: {DANGER}; color: white; border: none; border-radius: 10px; padding: 12px 22px;
    font-size: 15px; font-weight: 700; }}
QPushButton#danger:hover {{ background: #c92a2a; }}
QPushButton#link {{ border: none; background: transparent; color: {ACCENT}; padding: 2px; }}
QPushButton#link:hover {{ text-decoration: underline; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {SURFACE}; border: 1px solid #ccd2de; border-radius: 7px; padding: 5px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid {BORDER}; selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT}; }}
QRadioButton, QCheckBox {{ spacing: 8px; font-size: 13px; }}
QRadioButton#option {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 9px; padding: 9px 10px;
}}
QRadioButton#option:checked {{ border: 1px solid {ACCENT}; background: {ACCENT_SOFT}; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget#fileList {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px; }}
QListWidget#fileList::item {{ border-radius: 8px; padding: 6px; margin: 2px; }}
QListWidget#fileList::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}

QProgressBar {{ border: none; background: #e7eaf2; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QToolBar {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; spacing: 2px; padding: 4px 6px; }}
QToolBar QToolButton {{ border: 1px solid transparent; border-radius: 7px; padding: 5px; }}
QToolBar QToolButton:hover {{ background: #f1f3f8; }}
QToolBar QToolButton:checked {{ background: {ACCENT_SOFT}; border: 1px solid #c5d0fa; }}
QSlider::groove:horizontal {{ height: 4px; background: #dfe3ec; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: white; top: -1px; }}
QTabBar::tab {{ padding: 7px 14px; border: 1px solid transparent; border-top-left-radius: 7px;
    border-top-right-radius: 7px; color: {MUTED}; }}
QTabBar::tab:selected {{ background: white; border: 1px solid {BORDER}; border-bottom-color: white; color: {TEXT};
    font-weight: 600; }}
QToolTip {{ background: #1f2430; color: white; border: none; padding: 5px 8px; border-radius: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c9cfdb; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #aab2c3; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #c9cfdb; border-radius: 4px; min-width: 30px; }}
"""
