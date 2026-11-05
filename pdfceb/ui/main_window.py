"""Fenêtre principale : barre latérale, accueil et pages d'outils."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .. import __version__, core
from . import icons
from .editor import EditorWindow
from .style import ACCENT, CATEGORIES, MUTED, soft
from .tools import ALL_TOOLS
from .widgets import ask_password, error_box


class ToolCard(QFrame):
    clicked = Signal(str)

    def __init__(self, tool):
        super().__init__()
        self.setObjectName("card")
        self.key = tool.KEY
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(150)
        self.setMinimumWidth(210)
        color = CATEGORIES[tool.CAT][1]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(6)
        badge = QLabel()
        badge.setFixedSize(42, 42)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"background: {soft(color)}; border-radius: 11px; border: none;")
        badge.setPixmap(icons.pixmap(tool.ICON, color, 24))
        lay.addWidget(badge)
        t = QLabel(tool.TITLE)
        t.setStyleSheet("font-size: 14px; font-weight: 700; border: none; background: transparent;")
        lay.addWidget(t)
        d = QLabel(tool.DESC)
        d.setWordWrap(True)
        d.setStyleSheet(f"color: {MUTED}; font-size: 12px; border: none; background: transparent;")
        d.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(d, 1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.key)


class HomePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.setObjectName("page")
        self.main = main
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        inner = QWidget()
        inner.setObjectName("page")
        scroll.setWidget(inner)
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(36, 30, 36, 30)
        self.lay.setSpacing(8)
        h = QLabel("Toutes vos opérations PDF, au même endroit")
        h.setObjectName("h1")
        self.lay.addWidget(h)
        sub = QLabel("Fusionner, diviser, organiser, modifier, signer, caviarder… Tout est traité sur votre "
                     "ordinateur : aucun document n'est envoyé sur Internet.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        self.lay.addWidget(sub)
        self.cards: list[ToolCard] = []
        self.grids = []
        for cat, (label, color) in CATEGORIES.items():
            tools = [t for t in ALL_TOOLS if t.CAT == cat]
            if not tools:
                continue
            head = QLabel(label.upper())
            head.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 800; letter-spacing: 1px; "
                               f"padding-top: 18px;")
            self.lay.addWidget(head)
            grid = QGridLayout()
            grid.setSpacing(14)
            cards = []
            for t in tools:
                c = ToolCard(t)
                c.clicked.connect(main.open_tool)
                cards.append(c)
                self.cards.append(c)
            self.grids.append((grid, cards))
            self.lay.addLayout(grid)
        self.lay.addStretch(1)
        self._cols = 0

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cols = max(2, min(5, (self.width() - 72) // 250))
        if cols != self._cols:
            self._cols = cols
            for grid, cards in self.grids:
                for c in cards:
                    grid.removeWidget(c)
                for i, c in enumerate(cards):
                    grid.addWidget(c, i // cols, i % cols)
                for col in range(5):
                    grid.setColumnStretch(col, 1 if col < cols else 0)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Ceb")
        self.setWindowIcon(icons.app_icon())
        self.resize(1280, 840)
        self.setMinimumSize(980, 640)
        self.editors: list[EditorWindow] = []
        self.pages = {}

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(238)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 16, 12, 12)
        sl.setSpacing(1)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.app_pixmap(36))
        brand.addWidget(logo)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        name = QLabel("PDF Ceb")
        name.setObjectName("brand")
        bt.addWidget(name)
        v = QLabel(f"Boîte à outils PDF · v{__version__}")
        v.setObjectName("brandSub")
        bt.addWidget(v)
        brand.addLayout(bt, 1)
        sl.addLayout(brand)
        sl.addSpacing(12)

        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_inner = QWidget()
        side_inner.setStyleSheet("background: white;")
        si = QVBoxLayout(side_inner)
        si.setContentsMargins(0, 0, 4, 0)
        si.setSpacing(1)
        self.side_group = QButtonGroup(self)
        self.side_group.setExclusive(True)
        self.side_buttons = {}
        home = self._side_button("home", "Accueil", ACCENT)
        home.clicked.connect(self.show_home)
        si.addWidget(home)
        self.side_buttons["home"] = home
        for cat, (label, color) in CATEGORIES.items():
            lab = QLabel(label.upper())
            lab.setObjectName("sideSection")
            si.addWidget(lab)
            for t in [t for t in ALL_TOOLS if t.CAT == cat]:
                b = self._side_button(t.ICON, t.TITLE, color)
                b.clicked.connect(lambda _=False, k=t.KEY: self.open_tool(k))
                si.addWidget(b)
                self.side_buttons[t.KEY] = b
        si.addStretch(1)
        side_scroll.setWidget(side_inner)
        sl.addWidget(side_scroll, 1)
        root.addWidget(side)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.home = HomePage(self)
        self.stack.addWidget(self.home)
        self.setCentralWidget(central)
        self.show_home()

    def _side_button(self, icon_name, text, color):
        b = QPushButton(f"  {text}")
        b.setObjectName("sideButton")
        b.setIcon(icons.icon(icon_name, color, 18))
        b.setIconSize(QSize(18, 18))
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        self.side_group.addButton(b)
        return b

    def show_home(self):
        self.stack.setCurrentWidget(self.home)
        self.side_buttons["home"].setChecked(True)

    def tool_page(self, key):
        if key not in self.pages:
            cls = next(t for t in ALL_TOOLS if t.KEY == key)
            page = cls(self)
            self.pages[key] = page
            self.stack.addWidget(page)
        return self.pages[key]

    def open_tool(self, key, files=None):
        page = self.tool_page(key)
        self.stack.setCurrentWidget(page)
        self.side_buttons[key].setChecked(True)
        if files:
            page.load_files(files)
        return page

    def open_editor(self, path, password=None, mode="edit"):
        try:
            win = EditorWindow(path, password, mode)
        except Exception as exc:  # noqa: BLE001
            error_box(self, exc)
            return None
        self.editors.append(win)
        win.destroyed.connect(lambda *_: self.editors.remove(win) if win in self.editors else None)
        win.setAttribute(Qt.WA_DeleteOnClose, True)
        win.showMaximized()
        return win

    def open_files_from_args(self, paths):
        pdfs = [p for p in paths if core.is_pdf(p) and Path(p).exists()]
        if pdfs:
            pw = None
            if core.needs_password(pdfs[0]):
                pw = ask_password(self, pdfs[0])
                if pw is None:
                    return
            self.open_editor(pdfs[0], pw, "edit")

    def closeEvent(self, e):
        for w in list(self.editors):
            if not w.close():
                e.ignore()
                return
        for p in self.pages.values():
            if hasattr(p, "grid"):
                p.grid.clear_all()
        super().closeEvent(e)
