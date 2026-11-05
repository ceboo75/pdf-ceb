"""Création et mémorisation des signatures manuscrites."""
from __future__ import annotations

import io
import time
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRect, QRectF, QSize, QStandardPaths, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QTabWidget,
                               QVBoxLayout, QWidget)

from . import icons
from .widgets import IMG_FILTER, last_dir, remember_dir

SCRIPT_FONTS = ["Segoe Script", "Lucida Handwriting", "Ink Free", "Brush Script MT", "Mistral", "Freestyle Script",
                "Vladimir Script", "Edwardian Script ITC", "Kunstler Script", "Segoe Print", "Gabriola",
                "Bradley Hand ITC", "Comic Sans MS"]
INK_COLORS = {"Noir": "#111111", "Bleu": "#1c3faa"}
LIST_QSS = ("QListWidget { background: white; border: 1px solid #e1e5ee; border-radius: 8px; padding: 4px; }"
            "QListWidget::item { border: 1px solid transparent; border-radius: 8px; padding: 6px; margin: 2px; }"
            "QListWidget::item:selected { background: #edf2ff; border: 1px solid #4263eb; }"
            "QListWidget::item:hover { background: #f4f6fa; }")


def signatures_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or str(Path.home() / ".pdfceb")
    d = Path(base) / "signatures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def qimage_to_png(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def trim_transparent(img: QImage, pad: int = 8) -> QImage:
    """Recadre une image sur sa zone non transparente."""
    pil = Image.open(io.BytesIO(qimage_to_png(img))).convert("RGBA")
    bbox = pil.split()[-1].getbbox()
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(pil.width, x1 + pad), min(pil.height, y1 + pad)
    return img.copy(QRect(x0, y0, x1 - x0, y1 - y0))


class SignaturePad(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 220)
        self.strokes: list[list[QPointF]] = []
        self.color = QColor(INK_COLORS["Noir"])
        self.pen_width = 3.2
        self.setCursor(Qt.CrossCursor)

    def clear(self):
        self.strokes.clear()
        self.update()

    def is_empty(self):
        return not any(len(s) > 1 for s in self.strokes)

    def _path(self, pts, scale=1.0) -> QPainterPath:
        path = QPainterPath()
        if not pts:
            return path
        path.moveTo(pts[0] * scale)
        if len(pts) == 1:
            path.lineTo(pts[0] * scale + QPointF(0.1, 0.1))
            return path
        for i in range(1, len(pts) - 1):
            mid = (pts[i] + pts[i + 1]) / 2
            path.quadTo(pts[i] * scale, mid * scale)
        path.lineTo(pts[-1] * scale)
        return path

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QPen(QColor("#d5dae4"), 1))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)
        y = int(self.height() * 0.72)
        p.setPen(QPen(QColor("#c3cad9"), 1, Qt.DashLine))
        p.drawLine(30, y, self.width() - 30, y)
        if self.is_empty():
            p.setPen(QColor("#9aa1af"))
            p.drawText(self.rect().adjusted(0, 0, 0, -40), Qt.AlignCenter, "Signez ici avec la souris ou le pavé tactile")
        pen = QPen(self.color, self.pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        for s in self.strokes:
            p.drawPath(self._path(s))

    def mousePressEvent(self, e):
        self.strokes.append([e.position()])
        self.update()

    def mouseMoveEvent(self, e):
        if self.strokes and e.buttons() & Qt.LeftButton:
            pt = e.position()
            last = self.strokes[-1][-1]
            if (pt - last).manhattanLength() >= 1.5:
                self.strokes[-1].append(pt)
                self.update()

    def to_image(self) -> QImage:
        scale = 3.0
        img = QImage(int(self.width() * scale), int(self.height() * scale), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self.color, self.pen_width * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for s in self.strokes:
            p.drawPath(self._path(s, scale))
        p.end()
        return trim_transparent(img, 12)


def text_signature(text: str, family: str, color: str) -> QImage:
    font = QFont(family)
    font.setPixelSize(120)
    if family not in QFontDatabase.families():
        font.setItalic(True)
    from PySide6.QtGui import QFontMetrics
    fm = QFontMetrics(font)
    w = fm.horizontalAdvance(text) + 80
    h = fm.height() + 60
    img = QImage(max(w, 10), max(h, 10), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setFont(font)
    p.setPen(QColor(color))
    p.drawText(QRect(0, 0, w, h), Qt.AlignCenter, text)
    p.end()
    return trim_transparent(img, 10)


def image_signature(path: str, remove_white=True) -> QImage:
    pil = Image.open(path).convert("RGBA")
    if remove_white:
        px = pil.load()
        for y in range(pil.height):
            for x in range(pil.width):
                r, g, b, a = px[x, y]
                lum = (r * 299 + g * 587 + b * 114) / 1000
                if lum > 225:
                    px[x, y] = (r, g, b, 0)
                elif lum > 170:
                    px[x, y] = (r, g, b, int(a * (225 - lum) / 55))
    if max(pil.size) > 1600:
        pil.thumbnail((1600, 1600))
    buf = io.BytesIO()
    pil.save(buf, "PNG")
    img = QImage.fromData(buf.getvalue(), "PNG")
    return trim_transparent(img, 6)


class SignatureDialog(QDialog):
    """Renvoie une signature (PNG transparent) dans self.png / self.image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Votre signature")
        self.setMinimumWidth(720)
        self.png: bytes | None = None
        self.image: QImage | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        title = QLabel("Créez ou choisissez votre signature")
        title.setObjectName("h2")
        lay.addWidget(title)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        # --- dessiner
        w = QWidget()
        v = QVBoxLayout(w)
        self.pad = SignaturePad()
        v.addWidget(self.pad, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Encre :"))
        self.ink_group = QButtonGroup(self)
        for i, (name, col) in enumerate(INK_COLORS.items()):
            rb = QRadioButton(name)
            rb.setChecked(i == 0)
            rb.toggled.connect(lambda on, c=col: on and self._set_ink(c))
            self.ink_group.addButton(rb)
            row.addWidget(rb)
        row.addStretch(1)
        clear = QPushButton(icons.icon("undo", "#1f2430", 16), " Effacer")
        clear.clicked.connect(self.pad.clear)
        row.addWidget(clear)
        v.addLayout(row)
        self.tabs.addTab(w, "Dessiner")

        # --- saisir
        w = QWidget()
        v = QVBoxLayout(w)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Votre nom, par exemple : S. Martin")
        self.name_edit.textChanged.connect(self._refresh_fonts)
        v.addWidget(self.name_edit)
        self.font_list = QListWidget()
        self.font_list.setIconSize(QSize(420, 60))
        self.font_list.setMinimumHeight(220)
        self.font_list.setStyleSheet(LIST_QSS)
        v.addWidget(self.font_list, 1)
        fams = set(QFontDatabase.families())
        self.fonts = [f for f in SCRIPT_FONTS if f in fams] or ["Times New Roman"]
        self.tabs.addTab(w, "Saisir")

        # --- importer
        w = QWidget()
        v = QVBoxLayout(w)
        b = QPushButton(icons.icon("image", "#1f2430", 18), " Choisir une image de signature…")
        b.clicked.connect(self._import)
        v.addWidget(b, 0, Qt.AlignLeft)
        self.remove_white = QCheckBox("Rendre le fond blanc transparent")
        self.remove_white.setChecked(True)
        v.addWidget(self.remove_white)
        self.import_preview = QLabel("Aucune image choisie")
        self.import_preview.setAlignment(Qt.AlignCenter)
        self.import_preview.setMinimumHeight(180)
        self.import_preview.setStyleSheet("background: white; border: 1px solid #e1e5ee; border-radius: 8px;")
        v.addWidget(self.import_preview, 1)
        self._imported: QImage | None = None
        self.tabs.addTab(w, "Importer")

        # --- signatures mémorisées
        w = QWidget()
        v = QVBoxLayout(w)
        self.saved_list = QListWidget()
        self.saved_list.setIconSize(QSize(320, 90))
        self.saved_list.setStyleSheet(LIST_QSS)
        self.saved_list.itemDoubleClicked.connect(lambda _: self._accept())
        v.addWidget(self.saved_list, 1)
        delb = QPushButton(icons.icon("trash", "#1f2430", 16), " Supprimer la signature sélectionnée")
        delb.clicked.connect(self._delete_saved)
        v.addWidget(delb, 0, Qt.AlignLeft)
        self.saved_index = self.tabs.addTab(w, "Mes signatures")
        self._load_saved()

        bottom = QHBoxLayout()
        self.remember = QCheckBox("Mémoriser cette signature")
        self.remember.setChecked(True)
        bottom.addWidget(self.remember)
        bottom.addStretch(1)
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Utiliser cette signature")
        ok.setObjectName("primary")
        ok.clicked.connect(self._accept)
        bottom.addWidget(cancel)
        bottom.addWidget(ok)
        lay.addLayout(bottom)
        self.tabs.currentChanged.connect(lambda i: self.remember.setVisible(i != self.saved_index))
        if self.saved_list.count():
            self.tabs.setCurrentIndex(self.saved_index)
        self._refresh_fonts()

    def _set_ink(self, col):
        self.pad.color = QColor(col)
        self.pad.update()
        self._refresh_fonts()

    def _ink(self):
        return self.pad.color.name()

    def _refresh_fonts(self):
        text = self.name_edit.text().strip() or "Votre signature"
        cur = self.font_list.currentRow()
        self.font_list.clear()
        for fam in self.fonts:
            img = text_signature(text, fam, self._ink())
            pm = QPixmap.fromImage(img).scaled(420, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            it = QListWidgetItem(pm, "")
            it.setData(Qt.UserRole, fam)
            it.setToolTip(fam)
            self.font_list.addItem(it)
        self.font_list.setCurrentRow(max(0, cur))

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Image de signature", last_dir(), IMG_FILTER)
        if not path:
            return
        remember_dir(path)
        try:
            self._imported = image_signature(path, self.remove_white.isChecked())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Image illisible", str(exc))
            return
        self.import_preview.setPixmap(QPixmap.fromImage(self._imported).scaled(
            520, 170, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _load_saved(self):
        self.saved_list.clear()
        files = sorted(signatures_dir().glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files:
            img = QImage(str(f))
            if img.isNull():
                continue
            canvas = QPixmap(320, 90)
            canvas.fill(QColor("white"))
            pm = QPixmap.fromImage(img).scaled(300, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p = QPainter(canvas)
            p.drawPixmap((320 - pm.width()) // 2, (90 - pm.height()) // 2, pm)
            p.end()
            it = QListWidgetItem(canvas, "")
            it.setData(Qt.UserRole, str(f))
            self.saved_list.addItem(it)
        if self.saved_list.count():
            self.saved_list.setCurrentRow(0)
        self.tabs.setTabEnabled(self.saved_index, self.saved_list.count() > 0)

    def _delete_saved(self):
        it = self.saved_list.currentItem()
        if it:
            Path(it.data(Qt.UserRole)).unlink(missing_ok=True)
            self._load_saved()

    def _accept(self):
        idx = self.tabs.currentIndex()
        img = None
        if idx == 0:
            if self.pad.is_empty():
                QMessageBox.information(self, "Signature vide", "Dessinez votre signature dans le cadre.")
                return
            img = self.pad.to_image()
        elif idx == 1:
            if not self.name_edit.text().strip():
                QMessageBox.information(self, "Nom manquant", "Saisissez votre nom.")
                return
            it = self.font_list.currentItem()
            fam = it.data(Qt.UserRole) if it else self.fonts[0]
            img = text_signature(self.name_edit.text().strip(), fam, self._ink())
        elif idx == 2:
            if self._imported is None:
                QMessageBox.information(self, "Aucune image", "Choisissez d'abord une image.")
                return
            img = self._imported
        else:
            it = self.saved_list.currentItem()
            if not it:
                return
            img = QImage(it.data(Qt.UserRole))
        self.image = img
        self.png = qimage_to_png(img)
        if idx != self.saved_index and self.remember.isChecked():
            (signatures_dir() / f"signature_{int(time.time() * 1000)}.png").write_bytes(self.png)
        self.accept()
