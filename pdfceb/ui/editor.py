"""Éditeur visuel : ajout de texte, images, formes, signatures, surlignage,
cache blanc, commentaires et caviardage."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFont, QImage, QImageReader, QKeySequence,
                           QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QPolygonF, QShortcut,
                           QTransform)
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGraphicsItem,
                               QGraphicsObject, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsTextItem, QGraphicsView, QHBoxLayout, QInputDialog, QLabel, QListView,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QSizePolicy, QSpinBox, QToolBar, QToolButton, QVBoxLayout, QWidget)

from .. import core
from . import icons
from .signature import SignatureDialog, qimage_to_png
from .style import ACCENT, BG, DANGER, MUTED
from .widgets import (IMG_FILTER, PageRenderer, ResultDialog, ThumbGrid, ask_save_pdf, error_box, last_dir, remember_dir,
                      run_task, suggest_output)

GAP = 24.0
FONT_FAMILY = {"sans": "Arial", "serif": "Times New Roman", "mono": "Courier New"}
# décalage vertical (en fraction de taille) entre le rendu Qt et l'export PDF
BASELINE_FIX = {"sans": 0.02, "serif": 0.03, "mono": 0.08}
TEXT_MARGIN = 3.0

TOOLS = [
    ("select", "Sélection", "select", "Sélectionner, déplacer et redimensionner les éléments (Échap)"),
    ("text", "Texte", "text", "Cliquez dans la page pour écrire"),
    ("image", "Image", "image", "Insérer une image depuis votre ordinateur"),
    ("signature", "Signature", "sign", "Ajouter votre signature"),
    ("rect", "Rectangle", "rect", "Tracer un rectangle"),
    ("ellipse", "Ellipse", "ellipse", "Tracer une ellipse"),
    ("line", "Ligne", "line", "Tracer un trait"),
    ("arrow", "Flèche", "arrow", "Tracer une flèche"),
    ("ink", "Dessin", "ink", "Dessiner à main levée"),
    ("highlight", "Surligner", "highlight", "Surligner une zone de texte"),
    ("whiteout", "Cache blanc", "whiteout", "Masquer une zone avec un rectangle blanc (pour corriger un texte)"),
    ("note", "Commentaire", "note", "Ajouter une note (commentaire PDF)"),
    ("redact", "Caviarder", "redact", "Supprimer définitivement le contenu d'une zone"),
]

HINTS = {
    "select": "Cliquez sur un élément pour le sélectionner ; faites-le glisser pour le déplacer, tirez un coin pour le "
              "redimensionner. Double-cliquez sur un texte pour le modifier. Touche Suppr pour effacer.",
    "text": "Cliquez à l'endroit où écrire, puis tapez votre texte. Astuce : utilisez « Cache blanc » pour masquer "
            "un texte existant avant d'écrire par-dessus.",
    "rect": "Cliquez-glissez pour tracer un rectangle.",
    "ellipse": "Cliquez-glissez pour tracer une ellipse.",
    "line": "Cliquez-glissez pour tracer un trait.",
    "arrow": "Cliquez-glissez pour tracer une flèche.",
    "ink": "Maintenez le clic pour dessiner à main levée.",
    "highlight": "Cliquez-glissez sur le texte à surligner.",
    "whiteout": "Cliquez-glissez sur la zone à masquer. Le contenu reste présent dessous : pour le supprimer "
                "réellement, utilisez « Caviarder ».",
    "note": "Cliquez à l'endroit où placer le commentaire.",
    "redact": "Cliquez-glissez sur les zones à caviarder, ou utilisez « Rechercher et caviarder ». À l'enregistrement, "
              "le texte, les images et les tracés sous les zones noires sont supprimés définitivement.",
}


def _handle_size(item: QGraphicsItem) -> float:
    views = item.scene().views() if item.scene() else []
    z = views[0].transform().m11() if views else 1.0
    return 9.0 / max(z, 0.05)


def _with_alpha(color: str, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


# --------------------------------------------------------------------------
# Éléments ajoutés
# --------------------------------------------------------------------------
class Overlay:
    kind = ""

    def style(self) -> dict:
        return dict(self._style)

    def apply_style(self, st: dict):
        self._style.update({k: v for k, v in st.items() if k in self._style})
        self.update()


class BoxItem(QGraphicsObject, Overlay):
    """Élément rectangulaire : rectangle, ellipse, image, cache blanc, caviardage, surlignage."""

    def __init__(self, kind: str, rect: QRectF, style: dict | None = None, image: QImage | None = None,
                 data: bytes | None = None):
        super().__init__()
        self.kind = kind
        self._style = {"stroke": "#e03131", "fill": None, "width": 2.0, "opacity": 1.0, "color": "#ffe066"}
        if style:
            self._style.update({k: v for k, v in style.items() if k in self._style})
        self.image = image
        self.data = data
        self._r = QRectF(0, 0, max(1.0, rect.width()), max(1.0, rect.height()))
        self.setPos(rect.topLeft())
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self._drag = None
        self.keep_ratio = kind == "image"

    # géométrie
    def set_scene_rect(self, r: QRectF):
        self.prepareGeometryChange()
        r = r.normalized()
        self.setPos(r.topLeft())
        self._r = QRectF(0, 0, max(1.0, r.width()), max(1.0, r.height()))

    def page_rect(self) -> QRectF:
        return QRectF(self.pos() + self._r.topLeft(), self._r.size())

    def boundingRect(self):
        m = _handle_size(self) + float(self._style.get("width") or 0)
        return self._r.adjusted(-m, -m, m, m)

    def shape(self):
        path = QPainterPath()
        path.addRect(self._r.adjusted(-2, -2, 2, 2))
        return path

    def _handles(self):
        h = _handle_size(self)
        r = self._r
        return [QRectF(pt.x() - h / 2, pt.y() - h / 2, h, h)
                for pt in (r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft())]

    def paint(self, p: QPainter, opt, widget=None):
        st = self._style
        r = self._r
        p.setRenderHint(QPainter.Antialiasing)
        if self.kind in ("rect", "ellipse"):
            op = st["opacity"]
            pen = QPen(_with_alpha(st["stroke"], op), st["width"]) if st.get("stroke") else Qt.NoPen
            p.setPen(pen)
            p.setBrush(_with_alpha(st["fill"], op) if st.get("fill") else Qt.NoBrush)
            (p.drawRect if self.kind == "rect" else p.drawEllipse)(r)
        elif self.kind == "whiteout":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("white"))
            p.drawRect(r)
            p.setPen(QPen(QColor("#b8c0cc"), 0, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        elif self.kind == "redact":
            p.setPen(QPen(QColor(DANGER), 0, Qt.DashLine))
            p.setBrush(QColor(0, 0, 0, 205))
            p.drawRect(r)
        elif self.kind == "highlight":
            p.setCompositionMode(QPainter.CompositionMode_Multiply)
            p.setPen(Qt.NoPen)
            p.setBrush(_with_alpha(st["color"], 0.55))
            p.drawRect(r)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        elif self.kind == "image" and self.image is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.setOpacity(st["opacity"])
            p.drawImage(r, self.image)
            p.setOpacity(1.0)
        if self.isSelected():
            p.setPen(QPen(QColor(ACCENT), 0, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.setPen(QPen(QColor(ACCENT), 0))
            p.setBrush(QColor("white"))
            for h in self._handles():
                p.drawRect(h)

    def hoverMoveEvent(self, e):
        idx = self._handle_at(e.pos())
        if idx is None:
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.SizeFDiagCursor if idx in (0, 2) else Qt.SizeBDiagCursor)
        super().hoverMoveEvent(e)

    def _handle_at(self, pos):
        if not self.isSelected():
            return None
        for i, h in enumerate(self._handles()):
            if h.adjusted(-2, -2, 2, 2).contains(pos):
                return i
        return None

    def mousePressEvent(self, e):
        idx = self._handle_at(e.pos())
        if idx is not None and e.button() == Qt.LeftButton:
            self._drag = (idx, self.page_rect())
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag:
            idx, start = self._drag
            pt = self.mapToParent(e.pos())
            corners = [start.topLeft(), start.topRight(), start.bottomRight(), start.bottomLeft()]
            anchor = corners[(idx + 2) % 4]
            r = QRectF(anchor, pt).normalized()
            if self.keep_ratio != bool(e.modifiers() & Qt.ShiftModifier) and start.height() > 0:
                ratio = start.width() / start.height()
                w = max(r.width(), r.height() * ratio)
                h = w / ratio
                x = anchor.x() if pt.x() >= anchor.x() else anchor.x() - w
                y = anchor.y() if pt.y() >= anchor.y() else anchor.y() - h
                r = QRectF(x, y, w, h)
            if r.width() >= 4 and r.height() >= 4:
                self.set_scene_rect(r)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def to_edit(self) -> dict:
        r = self.page_rect()
        d = {"type": self.kind, "rect": (r.left(), r.top(), r.right(), r.bottom())}
        st = self._style
        if self.kind in ("rect", "ellipse"):
            d.update(stroke=st["stroke"], fill=st["fill"], width=st["width"], opacity=st["opacity"])
        elif self.kind == "highlight":
            d.update(color=st["color"])
        elif self.kind == "image":
            d.update(data=self.data, opacity=st["opacity"], force_png=False)
        return d


class TextItem(QGraphicsTextItem, Overlay):
    kind = "text"

    def __init__(self, text: str = "", style: dict | None = None):
        super().__init__(text)
        self._style = {"color": "#000000", "size": 14, "font": "sans", "bold": False, "italic": False,
                       "opacity": 1.0}
        if style:
            self._style.update({k: v for k, v in style.items() if k in self._style})
        self.document().setDocumentMargin(TEXT_MARGIN)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsFocusable)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.on_empty = None
        self._apply()

    def _apply(self):
        st = self._style
        f = QFont(FONT_FAMILY.get(st["font"], "Arial"))
        f.setPixelSize(int(st["size"]))
        f.setBold(bool(st["bold"]))
        f.setItalic(bool(st["italic"]))
        self.setFont(f)
        self.setDefaultTextColor(QColor(st["color"]))
        self.setOpacity(float(st["opacity"]))

    def apply_style(self, st: dict):
        self._style.update({k: v for k, v in st.items() if k in self._style})
        self._apply()

    def editing(self) -> bool:
        return bool(self.textInteractionFlags() & Qt.TextEditorInteraction)

    def start_edit(self, select_all=False):
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFocus(Qt.MouseFocusReason)
        cur = self.textCursor()
        if select_all:
            cur.select(cur.SelectionType.Document)
        else:
            cur.movePosition(cur.MoveOperation.End)
        self.setTextCursor(cur)

    def stop_edit(self):
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        cur = self.textCursor()
        cur.clearSelection()
        self.setTextCursor(cur)

    def mouseDoubleClickEvent(self, e):
        if not self.editing():
            self.start_edit()
        super().mouseDoubleClickEvent(e)

    def focusOutEvent(self, e):
        self.stop_edit()
        super().focusOutEvent(e)
        if not self.toPlainText().strip() and self.on_empty:
            QTimer.singleShot(0, lambda: self.on_empty(self))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.clearFocus()
            return
        super().keyPressEvent(e)

    def paint(self, p, opt, widget=None):
        from PySide6.QtWidgets import QStyle
        opt.state &= ~QStyle.State_Selected
        opt.state &= ~QStyle.State_HasFocus
        super().paint(p, opt, widget)
        if self.isSelected() or self.editing():
            p.setPen(QPen(QColor(ACCENT), 0, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.boundingRect())

    def to_edit(self) -> dict:
        st = self._style
        br = self.boundingRect()
        size = float(st["size"])
        fix = BASELINE_FIX.get(st["font"], 0.02) * size
        x0 = self.pos().x() + TEXT_MARGIN
        y0 = self.pos().y() + TEXT_MARGIN - fix
        x1 = self.pos().x() + br.width() - TEXT_MARGIN
        y1 = self.pos().y() + br.height() - TEXT_MARGIN
        return {"type": "text", "rect": (x0, y0, x1, y1), "text": self.toPlainText(), "size": size,
                "color": st["color"], "font": st["font"], "bold": st["bold"], "italic": st["italic"],
                "opacity": st["opacity"]}


class LineItem(QGraphicsObject, Overlay):
    def __init__(self, kind: str, p1: QPointF, style: dict | None = None):
        super().__init__()
        self.kind = kind
        self._style = {"stroke": "#e03131", "width": 2.0, "opacity": 1.0}
        if style:
            self._style.update({k: v for k, v in style.items() if k in self._style})
        self.p1 = QPointF(p1)
        self.p2 = QPointF(p1)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self._drag = None

    def set_end(self, p2: QPointF):
        self.prepareGeometryChange()
        self.p2 = QPointF(p2) - self.pos()

    def _head(self):
        a = math.atan2(self.p2.y() - self.p1.y(), self.p2.x() - self.p1.x())
        L = max(8.0, self._style["width"] * 4)
        left = QPointF(self.p2.x() - L * math.cos(a - 0.45), self.p2.y() - L * math.sin(a - 0.45))
        right = QPointF(self.p2.x() - L * math.cos(a + 0.45), self.p2.y() - L * math.sin(a + 0.45))
        return QPolygonF([left, self.p2, right])

    def boundingRect(self):
        m = _handle_size(self) + self._style["width"] * 4 + 4
        return QRectF(self.p1, self.p2).normalized().adjusted(-m, -m, m, m)

    def shape(self):
        path = QPainterPath(self.p1)
        path.lineTo(self.p2)
        s = QPainterPathStroker()
        s.setWidth(max(self._style["width"] + 6, _handle_size(self)))
        return s.createStroke(path)

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        col = _with_alpha(self._style["stroke"], self._style["opacity"])
        p.setPen(QPen(col, self._style["width"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(self.p1, self.p2)
        if self.kind == "arrow":
            p.setBrush(col)
            p.drawPolygon(self._head())
        if self.isSelected():
            h = _handle_size(self)
            p.setPen(QPen(QColor(ACCENT), 0))
            p.setBrush(QColor("white"))
            for pt in (self.p1, self.p2):
                p.drawEllipse(pt, h / 2, h / 2)

    def _end_at(self, pos):
        if not self.isSelected():
            return None
        h = _handle_size(self)
        for i, pt in enumerate((self.p1, self.p2)):
            if (pos - pt).manhattanLength() <= h:
                return i
        return None

    def hoverMoveEvent(self, e):
        self.setCursor(Qt.CrossCursor if self._end_at(e.pos()) is not None else Qt.SizeAllCursor)

    def mousePressEvent(self, e):
        idx = self._end_at(e.pos())
        if idx is not None:
            self._drag = idx
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.prepareGeometryChange()
            if self._drag == 0:
                self.p1 = e.pos()
            else:
                self.p2 = e.pos()
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def length(self):
        return math.hypot(self.p2.x() - self.p1.x(), self.p2.y() - self.p1.y())

    def to_edit(self) -> dict:
        a, b = self.p1 + self.pos(), self.p2 + self.pos()
        return {"type": self.kind, "p1": (a.x(), a.y()), "p2": (b.x(), b.y()), **self._style}


class InkItem(QGraphicsObject, Overlay):
    kind = "ink"

    def __init__(self, start: QPointF, style: dict | None = None):
        super().__init__()
        self._style = {"stroke": "#1c3faa", "width": 2.5, "opacity": 1.0}
        if style:
            self._style.update({k: v for k, v in style.items() if k in self._style})
        self.points = [QPointF(start)]
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        self.setCursor(Qt.SizeAllCursor)

    def add_point(self, pt: QPointF):
        if (pt - self.points[-1]).manhattanLength() >= 0.8:
            self.prepareGeometryChange()
            self.points.append(QPointF(pt))

    def _path(self):
        path = QPainterPath(self.points[0])
        for pt in self.points[1:]:
            path.lineTo(pt)
        return path

    def boundingRect(self):
        m = self._style["width"] + 4
        return self._path().boundingRect().adjusted(-m, -m, m, m)

    def shape(self):
        s = QPainterPathStroker()
        s.setWidth(self._style["width"] + 8)
        return s.createStroke(self._path())

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(_with_alpha(self._style["stroke"], self._style["opacity"]), self._style["width"],
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(self._path())
        if self.isSelected():
            p.setPen(QPen(QColor(ACCENT), 0, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self._path().boundingRect().adjusted(-3, -3, 3, 3))

    def to_edit(self) -> dict:
        pts = [(pt.x() + self.pos().x(), pt.y() + self.pos().y()) for pt in self.points]
        return {"type": "ink", "strokes": [pts], **self._style}


class NoteItem(QGraphicsObject, Overlay):
    kind = "note"
    SIZE = 20.0

    def __init__(self, text: str):
        super().__init__()
        self._style = {}
        self.text = text
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        self.setToolTip(text)
        self.setCursor(Qt.SizeAllCursor)

    def boundingRect(self):
        return QRectF(-2, -2, self.SIZE + 4, self.SIZE + 4)

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#b08900"), 1))
        p.setBrush(QColor("#ffe066"))
        path = QPainterPath()
        s = self.SIZE
        path.addRoundedRect(QRectF(0, 0, s, s * 0.75), 3, 3)
        path.moveTo(s * 0.25, s * 0.74)
        path.lineTo(s * 0.25, s)
        path.lineTo(s * 0.5, s * 0.74)
        p.drawPath(path.simplified())
        p.setPen(QPen(QColor("#7a5c00"), 1.2))
        p.drawLine(QPointF(s * 0.22, s * 0.28), QPointF(s * 0.78, s * 0.28))
        p.drawLine(QPointF(s * 0.22, s * 0.48), QPointF(s * 0.6, s * 0.48))
        if self.isSelected():
            p.setPen(QPen(QColor(ACCENT), 0, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.boundingRect())

    def mouseDoubleClickEvent(self, e):
        text, ok = QInputDialog.getMultiLineText(None, "Commentaire", "Texte du commentaire :", self.text)
        if ok:
            self.text = text
            self.setToolTip(text)

    def to_edit(self) -> dict:
        return {"type": "note", "point": (self.pos().x(), self.pos().y()), "text": self.text}


OVERLAYS = (BoxItem, TextItem, LineItem, InkItem, NoteItem)


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
class PageItem(QGraphicsRectItem):
    def __init__(self, pno: int, w: float, h: float):
        super().__init__(0, 0, w, h)
        self.pno = pno
        self.setBrush(QColor("white"))
        self.setPen(QPen(QColor("#cdd3de"), 0))
        self.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        self.pix = QGraphicsPixmapItem(self)
        self.pix.setTransformationMode(Qt.SmoothTransformation)
        self.pix.setZValue(-1000)
        self.scale_hi = 0.0
        self.low: QPixmap | None = None
        self.low_scale = 0.0
        self.pending = 0.0

    def overlays(self):
        return [c for c in self.childItems() if isinstance(c, OVERLAYS)]

    def set_render(self, pm: QPixmap, scale: float):
        self.pix.setPixmap(pm)
        self.pix.setScale(1.0 / scale)


class EditorView(QGraphicsView):
    zoom_changed = Signal(float)

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QColor("#e9ecf2"))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setFrameShape(QFrame.NoFrame)
        self.zoom = 1.0
        self._creating = None
        self._page = None
        self._start = None

    def set_zoom(self, z: float, anchor_mouse=False):
        z = max(0.2, min(5.0, z))
        if not anchor_mouse:
            self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setTransform(QTransform.fromScale(z, z))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.zoom = z
        self.zoom_changed.emit(z)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self.zoom * factor, anchor_mouse=True)
            e.accept()
            return
        super().wheelEvent(e)

    def mousePressEvent(self, e):
        tool = self.editor.tool
        if e.button() != Qt.LeftButton or tool == "select":
            return super().mousePressEvent(e)
        sp = self.mapToScene(e.position().toPoint())
        page = self.editor.page_at(sp)
        if page is None:
            return super().mousePressEvent(e)
        under = self.itemAt(e.position().toPoint())
        if isinstance(under, OVERLAYS) and under.isSelected() and not isinstance(under, TextItem):
            return super().mousePressEvent(e)  # ajuster l'élément qui vient d'être tracé
        if tool == "text" and isinstance(under, TextItem):
            self.scene().clearSelection()
            under.setSelected(True)
            under.start_edit()
            return
        if self.scene().focusItem() and isinstance(self.scene().focusItem(), TextItem) and \
                self.scene().focusItem().editing():
            self.scene().focusItem().clearFocus()
            if tool == "text":
                return
        lp = page.mapFromScene(sp)
        self._creating = self.editor.begin_create(tool, page, lp)
        self._page = page
        self._start = lp
        e.accept()

    def mouseMoveEvent(self, e):
        if self._creating is not None:
            lp = self._page.mapFromScene(self.mapToScene(e.position().toPoint()))
            r = self._page.rect()
            lp = QPointF(min(max(lp.x(), r.left()), r.right()), min(max(lp.y(), r.top()), r.bottom()))
            self.editor.update_create(self._creating, self._start, lp)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._creating is not None:
            item = self._creating
            self._creating = None
            self.editor.end_create(item)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        fi = self.scene().focusItem()
        if isinstance(fi, TextItem) and fi.editing():
            return super().keyPressEvent(e)
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.editor.delete_selected()
            return
        if e.key() == Qt.Key_Escape:
            self.scene().clearSelection()
            self.editor.set_tool("select")
            return
        if e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and self.scene().selectedItems():
            step = 5.0 if e.modifiers() & Qt.ShiftModifier else 1.0
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(e.key(), 0.0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(e.key(), 0.0)
            for it in self.scene().selectedItems():
                it.moveBy(dx, dy)
            return
        super().keyPressEvent(e)


class ColorButton(QToolButton):
    color_changed = Signal(object)

    def __init__(self, color: str | None, allow_none=False, tooltip=""):
        super().__init__()
        self.allow_none = allow_none
        self.setToolTip(tooltip)
        self.setPopupMode(QToolButton.InstantPopup if allow_none else QToolButton.DelayedPopup)
        self._color = color
        if allow_none:
            from PySide6.QtWidgets import QMenu
            m = QMenu(self)
            m.addAction("Aucun remplissage", lambda: self.set_color(None, emit=True))
            m.addAction("Choisir une couleur…", self._choose)
            self.setMenu(m)
        else:
            self.clicked.connect(self._choose)
        self._refresh()

    def _choose(self):
        c = QColorDialog.getColor(QColor(self._color or "#000000"), self, "Couleur")
        if c.isValid():
            self.set_color(c.name(), emit=True)

    def set_color(self, color, emit=False):
        self._color = color
        self._refresh()
        if emit:
            self.color_changed.emit(color)

    def color(self):
        return self._color

    def _refresh(self):
        pm = QPixmap(22, 22)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#9aa1af"), 1))
        if self._color:
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(QRectF(2, 2, 18, 18), 4, 4)
        else:
            p.setBrush(QColor("white"))
            p.drawRoundedRect(QRectF(2, 2, 18, 18), 4, 4)
            p.setPen(QPen(QColor(DANGER), 1.6))
            p.drawLine(QPointF(5, 17), QPointF(17, 5))
        p.end()
        self.setIcon(pm)


# --------------------------------------------------------------------------
# Fenêtre de l'éditeur
# --------------------------------------------------------------------------
class EditorWindow(QMainWindow):
    saved = Signal(str)

    def __init__(self, path, password=None, mode="edit", parent=None):
        super().__init__(parent)
        self.path = str(path)
        self.password = password
        self.mode = mode
        self.tool = "select"
        self.history: list = []
        self.dirty = False
        self._saving = False
        self._closing = False
        self.colors = {"text": "#000000", "shape": "#e03131", "ink": "#1c3faa", "highlight": "#ffe066"}
        self.fill = None
        self.width_ = 2.0
        self.text_style = {"size": 14, "font": "sans", "bold": False, "italic": False}
        self.opacity = 1.0
        titles = {"edit": "Modifier", "sign": "Signer", "redact": "Caviarder"}
        self.setWindowTitle(f"{titles.get(mode, 'Modifier')} — {Path(path).name} — PDF Ceb")
        self.setWindowIcon(icons.app_icon())
        self.resize(1320, 880)

        doc = core.open_pdf(path, password)
        self.sizes = [(p.rect.width, p.rect.height) for p in doc]
        doc.close()

        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QColor("#e9ecf2"))
        self.view = EditorView(self)
        self.view.setScene(self.scene)
        self.pages: list[PageItem] = []
        maxw = max(w for w, _ in self.sizes)
        y = 0.0
        for i, (w, h) in enumerate(self.sizes):
            pg = PageItem(i, w, h)
            pg.setPos((maxw - w) / 2, y)
            self.scene.addItem(pg)
            self.pages.append(pg)
            y += h + GAP
        self.scene.setSceneRect(QRectF(-GAP * 2, -GAP, maxw + GAP * 4, y + GAP))
        self.scene.selectionChanged.connect(self._sync_style_controls)

        self._build_ui()

        data = Path(path).read_bytes()
        self.hi = PageRenderer(path, password, data=data, parent=self)
        self.hi.rendered.connect(self._on_rendered)
        self.lo = PageRenderer(path, password, data=data, parent=self)
        self.lo.rendered.connect(self._on_rendered)
        for i, (w, h) in enumerate(self.sizes):
            self.lo.request("low", i, 150 / max(w, h))
        self.hi.start()
        self.lo.start()
        self._render_timer = QTimer(self, singleShot=True, interval=90)
        self._render_timer.timeout.connect(self._render_visible)
        self.view.verticalScrollBar().valueChanged.connect(lambda _: self._schedule())
        self.view.horizontalScrollBar().valueChanged.connect(lambda _: self._schedule())
        self.view.zoom_changed.connect(self._on_zoom)
        QTimer.singleShot(0, self.fit_width)

        self.set_tool("select")
        if mode == "redact":
            self.set_tool("redact")
        elif mode == "sign":
            QTimer.singleShot(250, lambda: self.set_tool("signature"))

    # ------------------------------------------------------------- interface
    def _build_ui(self):
        tb = QToolBar("Outils")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.addToolBar(Qt.TopToolBarArea, tb)
        self.tool_actions = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for key, label, ic, tip in TOOLS:
            if key == "redact" and self.mode not in ("redact",):
                tb.addSeparator()
            color = DANGER if key == "redact" else "#1f2430"
            a = QAction(icons.icon(ic, color, 20), label, self)
            a.setCheckable(True)
            a.setToolTip(tip)
            a.triggered.connect(lambda _=False, k=key: self.set_tool(k))
            group.addAction(a)
            tb.addAction(a)
            self.tool_actions[key] = a
        self.search_btn = QPushButton(icons.icon("search", DANGER, 18), " Rechercher et caviarder…")
        self.search_btn.setToolTip("Caviarder toutes les occurrences d'un mot ou d'une expression")
        self.search_btn.clicked.connect(self.search_redact)
        self.save_btn = QPushButton(icons.icon("save", "#ffffff", 18), "  Enregistrer le PDF")
        self.save_btn.setObjectName("primary")
        self.save_btn.setShortcut(QKeySequence.Save)
        self.save_btn.setToolTip("Enregistrer une copie modifiée (Ctrl+S)")
        self.save_btn.clicked.connect(self.save)

        # barre de style
        sb = QToolBar("Style")
        sb.setMovable(False)
        sb.setIconSize(QSize(18, 18))
        self.addToolBarBreak()
        self.addToolBar(Qt.TopToolBarArea, sb)
        a = QAction(icons.icon("undo", "#1f2430", 18), "Annuler", self)
        a.setShortcut(QKeySequence.Undo)
        a.setToolTip("Annuler (Ctrl+Z)")
        a.triggered.connect(self.undo)
        sb.addAction(a)
        a = QAction(icons.icon("trash", "#1f2430", 18), "Supprimer", self)
        a.setToolTip("Supprimer l'élément sélectionné (Suppr)")
        a.triggered.connect(self.delete_selected)
        sb.addAction(a)
        sb.addSeparator()
        self.style_widgets = {}

        def add_labeled(label, w, key):
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(6, 0, 6, 0)
            h.setSpacing(5)
            lab = QLabel(label)
            lab.setObjectName("hint")
            h.addWidget(lab)
            h.addWidget(w)
            act = sb.addWidget(box)
            self.style_widgets[key] = act
            return w

        self.color_btn = add_labeled("Couleur", ColorButton("#000000", tooltip="Couleur du trait ou du texte"), "color")
        self.color_btn.color_changed.connect(self._on_color)
        self.fill_btn = add_labeled("Remplissage", ColorButton(None, allow_none=True, tooltip="Remplissage"), "fill")
        self.fill_btn.color_changed.connect(self._on_fill)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 20)
        self.width_spin.setValue(2)
        self.width_spin.setSuffix(" pt")
        self.width_spin.valueChanged.connect(self._on_width)
        add_labeled("Épaisseur", self.width_spin, "width")
        self.font_combo = QComboBox()
        self.font_combo.addItem("Arial / Helvetica", "sans")
        self.font_combo.addItem("Times", "serif")
        self.font_combo.addItem("Courier", "mono")
        self.font_combo.currentIndexChanged.connect(self._on_text_style)
        add_labeled("Police", self.font_combo, "font")
        self.size_spin = QSpinBox()
        self.size_spin.setRange(5, 120)
        self.size_spin.setValue(14)
        self.size_spin.valueChanged.connect(self._on_text_style)
        add_labeled("Taille", self.size_spin, "size")
        self.bold_btn = QToolButton()
        self.bold_btn.setText("G")
        self.bold_btn.setCheckable(True)
        self.bold_btn.setToolTip("Gras")
        self.bold_btn.setStyleSheet("font-weight: 800; min-width: 22px;")
        self.bold_btn.toggled.connect(self._on_text_style)
        self.style_widgets["bold"] = sb.addWidget(self.bold_btn)
        self.italic_btn = QToolButton()
        self.italic_btn.setText("I")
        self.italic_btn.setCheckable(True)
        self.italic_btn.setToolTip("Italique")
        self.italic_btn.setStyleSheet("font-style: italic; font-family: serif; min-width: 22px;")
        self.italic_btn.toggled.connect(self._on_text_style)
        self.style_widgets["italic"] = sb.addWidget(self.italic_btn)
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(10, 100)
        self.opacity_spin.setValue(100)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.valueChanged.connect(self._on_opacity)
        add_labeled("Opacité", self.opacity_spin, "opacity")
        self.scrub_check = QCheckBox("Effacer aussi les métadonnées (auteur, titre…)")
        self.scrub_check.setChecked(True)
        self.style_widgets["scrub"] = sb.addWidget(self.scrub_check)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sb.addWidget(spacer)
        self.page_label = QLabel()
        self.page_label.setObjectName("muted")
        sb.addWidget(self.page_label)
        sb.addSeparator()
        for ic, tip, fn in (("zoom_out", "Zoom arrière (Ctrl+molette)", lambda: self.view.set_zoom(self.view.zoom / 1.2)),
                            ("zoom_in", "Zoom avant (Ctrl+molette)", lambda: self.view.set_zoom(self.view.zoom * 1.2)),
                            ("fit", "Ajuster à la largeur", self.fit_width)):
            a = QAction(icons.icon(ic, "#1f2430", 18), tip, self)
            a.triggered.connect(fn)
            sb.addAction(a)
            if ic == "zoom_out":
                self.zoom_label = QLabel("100 %")
                self.zoom_label.setMinimumWidth(48)
                self.zoom_label.setAlignment(Qt.AlignCenter)
        sb.insertWidget(sb.actions()[-2], self.zoom_label)

        # zone centrale : vignettes + vue + bandeau
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.banner = QFrame()
        self.banner.setObjectName("infoBanner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(12, 7, 12, 7)
        self.banner_icon = QLabel()
        bl.addWidget(self.banner_icon)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(self.search_btn)
        bl.addSpacing(6)
        bl.addWidget(self.save_btn)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(10, 8, 10, 0)
        hl.addWidget(self.banner)
        lay.addWidget(holder)
        body = QHBoxLayout()
        body.setContentsMargins(0, 8, 0, 0)
        body.setSpacing(0)
        self.thumbs = ThumbGrid("select", False, cell=QSize(146, 186), vertical=True)
        self.thumbs.setSelectionMode(QListWidget.SingleSelection)
        self.thumbs.setFixedWidth(172)
        self.thumbs.setStyleSheet("QListWidget { background: #f4f6fa; border-right: 1px solid #e1e5ee; }")
        self.thumbs.add_document(self.path, self.password)
        self.thumbs.relabel()
        self.thumbs.itemClicked.connect(lambda it: self.goto_page(self.thumbs.row(it)))
        body.addWidget(self.thumbs)
        body.addWidget(self.view, 1)
        lay.addLayout(body, 1)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setVisible(False)
        self.busy.setFixedHeight(5)
        self.busy.setTextVisible(False)
        lay.addWidget(self.busy)
        self.setCentralWidget(central)

    # --------------------------------------------------------------- rendu
    def _schedule(self):
        if self._closing:
            return
        self._render_timer.start()
        self._update_page_label()

    def _on_zoom(self, z):
        self.zoom_label.setText(f"{round(z * 100)} %")
        self._schedule()

    def fit_width(self):
        maxw = max(w for w, _ in self.sizes)
        avail = max(200, self.view.viewport().width() - 60)
        self.view.set_zoom(min(2.0, avail / maxw))

    def visible_pages(self, margin=0.6):
        vr = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        ext = vr.adjusted(0, -vr.height() * margin, 0, vr.height() * margin)
        return [p for p in self.pages if p.sceneBoundingRect().intersects(ext)]

    def current_page(self) -> PageItem:
        vr = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        c = vr.center()
        best = min(self.pages, key=lambda p: abs(p.sceneBoundingRect().center().y() - c.y()))
        for p in self.pages:
            if p.sceneBoundingRect().contains(c):
                return p
        return best

    def _update_page_label(self):
        if self.pages:
            cp = self.current_page()
            self.page_label.setText(f"Page {cp.pno + 1} / {len(self.pages)}   ")
            if self.thumbs.currentRow() != cp.pno and cp.pno < self.thumbs.count():
                self.thumbs.blockSignals(True)
                self.thumbs.setCurrentRow(cp.pno)
                self.thumbs.scrollToItem(self.thumbs.item(cp.pno))
                self.thumbs.blockSignals(False)

    def _render_visible(self):
        dpr = self.view.devicePixelRatioF() if hasattr(self.view, "devicePixelRatioF") else 1.0
        need = min(4.0, max(0.3, self.view.zoom * dpr))
        visible = set(self.visible_pages())
        self.hi.clear()
        for p in visible:
            if abs(p.scale_hi - need) / need > 0.12:
                p.pending = need
                self.hi.request("hi", p.pno, need)
        for p in self.pages:
            if p not in visible and p.scale_hi and p.low is not None:
                p.set_render(p.low, p.low_scale)
                p.scale_hi = 0.0

    def _on_rendered(self, tag, pno, scale, img):
        if self._closing or pno >= len(self.pages):
            return
        page = self.pages[pno]
        pm = QPixmap.fromImage(img)
        if tag == "low":
            page.low = pm
            page.low_scale = scale
            if not page.scale_hi:
                page.set_render(pm, scale)
        else:
            if abs(scale - page.pending) < 1e-6:
                page.set_render(pm, scale)
                page.scale_hi = scale

    def goto_page(self, pno: int):
        p = self.pages[pno]
        r = p.sceneBoundingRect()
        self.view.centerOn(r.center().x(), r.top() + self.view.viewport().height() / (2 * self.view.zoom) - 10)

    def page_at(self, sp: QPointF) -> PageItem | None:
        for p in self.pages:
            if p.sceneBoundingRect().contains(sp):
                return p
        return None

    # --------------------------------------------------------------- outils
    def set_tool(self, key: str):
        if key in ("image", "signature"):
            self.tool_actions[key].setChecked(False)
            self.tool_actions[self.tool].setChecked(True)
            (self.insert_image if key == "image" else self.insert_signature)()
            return
        self.tool = key
        self.tool_actions[key].setChecked(True)
        self.view.setDragMode(QGraphicsView.RubberBandDrag if key == "select" else QGraphicsView.NoDrag)
        self.view.viewport().setCursor(Qt.ArrowCursor if key == "select" else
                                       (Qt.IBeamCursor if key == "text" else Qt.CrossCursor))
        hint = HINTS.get(key, "")
        self.banner_text.setText(hint)
        self.search_btn.setVisible(key == "redact" or self.mode == "redact")
        warn = key in ("redact", "whiteout")
        self.banner.setObjectName("banner" if warn else "infoBanner")
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner_icon.setPixmap(icons.pixmap("shield" if key == "redact" else "edit", DANGER if warn else ACCENT, 18))
        self._refresh_style_bar()

    def _color_key(self, kind=None):
        k = kind or self.tool
        if k == "text":
            return "text"
        if k == "ink":
            return "ink"
        if k == "highlight":
            return "highlight"
        return "shape"

    def _refresh_style_bar(self, item=None):
        kind = item.kind if item is not None else self.tool
        show = {
            "text": {"color", "font", "size", "bold", "italic", "opacity"},
            "rect": {"color", "fill", "width", "opacity"},
            "ellipse": {"color", "fill", "width", "opacity"},
            "line": {"color", "width", "opacity"},
            "arrow": {"color", "width", "opacity"},
            "ink": {"color", "width", "opacity"},
            "highlight": {"color"},
            "image": {"opacity"},
            "redact": {"scrub"},
        }.get(kind, set())
        if kind == "select" and item is None:
            show = set()
        if self.mode == "redact" or any(isinstance(i, BoxItem) and i.kind == "redact" for p in self.pages
                                        for i in p.overlays()):
            show = show | {"scrub"}
        for key, act in self.style_widgets.items():
            act.setVisible(key in show)
        if item is None:
            self.color_btn.set_color(self.colors[self._color_key()])

    def _style_for(self, kind):
        ck = self._color_key(kind)
        st = {"opacity": self.opacity, "width": self.width_}
        if kind == "text":
            st.update(color=self.colors["text"], **self.text_style)
        elif kind == "highlight":
            st.update(color=self.colors["highlight"])
        elif kind in ("rect", "ellipse"):
            st.update(stroke=self.colors[ck], fill=self.fill)
        else:
            st.update(stroke=self.colors[ck])
        return st

    def _sync_style_controls(self):
        items = [i for i in self.scene.selectedItems() if isinstance(i, OVERLAYS)]
        if len(items) != 1:
            self._refresh_style_bar()
            return
        it = items[0]
        st = it.style()
        self._refresh_style_bar(it)
        for w in (self.color_btn, self.fill_btn, self.width_spin, self.font_combo, self.size_spin, self.bold_btn,
                  self.italic_btn, self.opacity_spin):
            w.blockSignals(True)
        if "color" in st and it.kind in ("text", "highlight"):
            self.color_btn.set_color(st["color"])
        elif "stroke" in st:
            self.color_btn.set_color(st["stroke"])
        if "fill" in st:
            self.fill_btn.set_color(st["fill"])
        if "width" in st:
            self.width_spin.setValue(int(round(st["width"])))
        if "opacity" in st:
            self.opacity_spin.setValue(int(round(st["opacity"] * 100)))
        if it.kind == "text":
            self.font_combo.setCurrentIndex(max(0, self.font_combo.findData(st["font"])))
            self.size_spin.setValue(int(st["size"]))
            self.bold_btn.setChecked(bool(st["bold"]))
            self.italic_btn.setChecked(bool(st["italic"]))
        for w in (self.color_btn, self.fill_btn, self.width_spin, self.font_combo, self.size_spin, self.bold_btn,
                  self.italic_btn, self.opacity_spin):
            w.blockSignals(False)

    def _selected(self):
        return [i for i in self.scene.selectedItems() if isinstance(i, OVERLAYS)]

    def _on_color(self, c):
        sel = self._selected()
        if sel:
            for it in sel:
                key = "color" if it.kind in ("text", "highlight") else "stroke"
                it.apply_style({key: c})
                self.colors[self._color_key(it.kind)] = c
        else:
            self.colors[self._color_key()] = c
        self.dirty = self.dirty or bool(sel)

    def _on_fill(self, c):
        self.fill = c
        for it in self._selected():
            it.apply_style({"fill": c})

    def _on_width(self, v):
        self.width_ = float(v)
        for it in self._selected():
            if hasattr(it, "prepareGeometryChange"):
                it.prepareGeometryChange()
            it.apply_style({"width": float(v)})

    def _on_opacity(self, v):
        self.opacity = v / 100
        for it in self._selected():
            it.apply_style({"opacity": v / 100})

    def _on_text_style(self, *_):
        self.text_style = {"size": self.size_spin.value(), "font": self.font_combo.currentData(),
                           "bold": self.bold_btn.isChecked(), "italic": self.italic_btn.isChecked()}
        for it in self._selected():
            if isinstance(it, TextItem):
                it.apply_style(self.text_style)

    # ------------------------------------------------------- création
    def _add(self, item, page: PageItem):
        item.setParentItem(page)
        item.setZValue(len(page.overlays()))
        self.history.append(("add", item, page))
        self.dirty = True
        if isinstance(item, TextItem):
            item.on_empty = self._remove_silently
        return item

    def _remove_silently(self, item):
        if item.scene() is not None:
            page = item.parentItem()
            self.scene.removeItem(item)
            self.history = [h for h in self.history if h[1] is not item]

    def begin_create(self, tool, page: PageItem, lp: QPointF):
        if tool == "text":
            it = TextItem("", self._style_for("text"))
            it.setPos(lp - QPointF(TEXT_MARGIN, TEXT_MARGIN + self.text_style["size"] * 0.55))
            self._add(it, page)
            self.scene.clearSelection()
            it.setSelected(True)
            it.start_edit()
            return None
        if tool == "note":
            text, ok = QInputDialog.getMultiLineText(self, "Commentaire", "Texte du commentaire :")
            if ok and text.strip():
                it = NoteItem(text.strip())
                it.setPos(lp - QPointF(NoteItem.SIZE / 2, NoteItem.SIZE / 2))
                self._add(it, page)
            return None
        if tool in ("rect", "ellipse", "whiteout", "redact", "highlight"):
            it = BoxItem(tool, QRectF(lp, lp), self._style_for(tool))
            self._add(it, page)
            return it
        if tool in ("line", "arrow"):
            it = LineItem(tool, lp, self._style_for(tool))
            self._add(it, page)
            return it
        if tool == "ink":
            it = InkItem(lp, self._style_for("ink"))
            self._add(it, page)
            return it
        return None

    def update_create(self, item, start: QPointF, lp: QPointF):
        if isinstance(item, BoxItem):
            item.set_scene_rect(QRectF(start, lp))
        elif isinstance(item, LineItem):
            item.set_end(lp)
        elif isinstance(item, InkItem):
            item.add_point(lp)

    def end_create(self, item):
        too_small = (isinstance(item, BoxItem) and (item._r.width() < 3 or item._r.height() < 3)) or \
                    (isinstance(item, LineItem) and item.length() < 3)
        if too_small:
            self._remove_silently(item)
            return
        if not isinstance(item, InkItem):
            self.scene.clearSelection()
            item.setSelected(True)
        self._refresh_style_bar()

    def _place_box(self, kind, img: QImage, data: bytes, width_pt: float):
        page = self.current_page()
        w = min(width_pt, page.rect().width() * 0.8)
        h = w * img.height() / max(1, img.width())
        if h > page.rect().height() * 0.8:
            h = page.rect().height() * 0.8
            w = h * img.width() / max(1, img.height())
        vr = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        c = page.mapFromScene(vr.center())
        r = page.rect()
        cx = min(max(c.x(), r.left() + w / 2), r.right() - w / 2)
        cy = min(max(c.y(), r.top() + h / 2), r.bottom() - h / 2)
        it = BoxItem("image", QRectF(cx - w / 2, cy - h / 2, w, h), {"opacity": 1.0}, image=img, data=data)
        self._add(it, page)
        self.scene.clearSelection()
        it.setSelected(True)
        self.set_tool("select")
        self.view.setFocus()
        return it

    def insert_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Insérer une image", last_dir(), IMG_FILTER)
        if not path:
            return
        remember_dir(path)
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            QMessageBox.warning(self, "Image illisible", "Impossible de lire cette image.")
            return
        if max(img.width(), img.height()) > 3000:
            img = img.scaled(3000, 3000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        if Path(path).suffix.lower() in (".jpg", ".jpeg") and not img.hasAlphaChannel():
            img.save(buf, "JPEG", 92)
        else:
            img.save(buf, "PNG")
        buf.close()
        self._place_box("image", img, bytes(ba), 180)

    def insert_signature(self):
        dlg = SignatureDialog(self)
        if dlg.exec() and dlg.png:
            it = self._place_box("image", dlg.image, dlg.png, 150)
            self.banner_text.setText("Faites glisser la signature à l'emplacement voulu et ajustez sa taille avec les "
                                     "coins. Vous pouvez en ajouter d'autres avec le bouton « Signature ».")
            return it
        return None

    def search_redact(self):
        term, ok = QInputDialog.getText(self, "Rechercher et caviarder",
                                        "Mot ou expression à caviarder dans tout le document :")
        if not ok or not term.strip():
            return
        try:
            found = core.search_text_rects(self.path, self.password, term)
        except Exception as exc:  # noqa: BLE001
            error_box(self, exc)
            return
        n = 0
        for pno, rects in found.items():
            for r in rects:
                rr = QRectF(QPointF(r[0], r[1]), QPointF(r[2], r[3])).adjusted(-1, -1, 1, 1)
                self._add(BoxItem("redact", rr), self.pages[pno])
                n += 1
        if n:
            first = min(found)
            self.goto_page(first)
            QMessageBox.information(self, "Caviardage", f"{n} occurrence(s) de « {term} » marquée(s) sur "
                                    f"{len(found)} page(s).\nVérifiez puis cliquez sur « Enregistrer le PDF ».")
        else:
            QMessageBox.information(self, "Caviardage", f"« {term} » n'a pas été trouvé dans le texte du document.\n"
                                    "S'il s'agit d'un document scanné, tracez les zones à la main.")
        self._refresh_style_bar()

    def delete_selected(self):
        for it in self._selected():
            page = it.parentItem()
            self.scene.removeItem(it)
            self.history.append(("remove", it, page))
            self.dirty = True

    def undo(self):
        fi = self.scene.focusItem()
        if isinstance(fi, TextItem) and fi.editing():
            fi.document().undo()
            return
        while self.history:
            op, item, page = self.history.pop()
            if op == "add":
                if item.scene() is not None:
                    self.scene.removeItem(item)
                    return
            else:
                item.setParentItem(page)
                return

    # ------------------------------------------------------- enregistrement
    def collect_edits(self) -> dict:
        fi = self.scene.focusItem()
        if isinstance(fi, TextItem):
            fi.clearFocus()
        edits = {}
        for page in self.pages:
            items = sorted(page.overlays(), key=lambda i: i.zValue())
            data = [i.to_edit() for i in items]
            data = [d for d in data if not (d["type"] == "text" and not d["text"].strip())]
            if data:
                edits[page.pno] = data
        return edits

    def save(self):
        if self._saving:
            return
        edits = self.collect_edits()
        if not edits:
            QMessageBox.information(self, "Rien à enregistrer", "Vous n'avez encore rien ajouté au document.")
            return
        has_redact = any(d["type"] == "redact" for v in edits.values() for d in v)
        if has_redact:
            ans = QMessageBox.question(
                self, "Caviardage définitif",
                "Le contenu situé sous les zones noires sera supprimé définitivement du fichier enregistré "
                "(texte, images et tracés). Le fichier d'origine n'est pas modifié si vous l'enregistrez sous un "
                "autre nom.\n\nContinuer ?")
            if ans != QMessageBox.Yes:
                return
        suffix = {"sign": "signé", "redact": "caviardé"}.get(self.mode, "modifié")
        if has_redact and self.mode != "redact":
            suffix = "caviardé"
        out = ask_save_pdf(self, suggest_output(self.path, suffix))
        if not out:
            return
        self._saving = True
        self.busy.setVisible(True)
        self.save_btn.setEnabled(False)
        scrub = self.scrub_check.isChecked()

        def done(res):
            self._saving = False
            self.busy.setVisible(False)
            self.save_btn.setEnabled(True)
            self.dirty = False
            self.saved.emit(res)
            msg = "Les modifications ont été appliquées."
            if has_redact:
                msg = "Le caviardage est appliqué : le contenu masqué a été supprimé du fichier."
            ResultDialog(self, "Votre PDF est prêt", msg, [res]).exec()

        def fail(exc):
            self._saving = False
            self.busy.setVisible(False)
            self.save_btn.setEnabled(True)
            error_box(self, exc)

        run_task(core.apply_edits, self.path, self.password, out, edits, scrub_metadata=scrub,
                 on_done=done, on_error=fail)

    def closeEvent(self, e):
        if self._saving:
            e.ignore()
            return
        if self.dirty and any(p.overlays() for p in self.pages):
            ans = QMessageBox.question(self, "Modifications non enregistrées",
                                       "Vous avez des modifications non enregistrées. Fermer quand même ?",
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                e.ignore()
                return
        self._closing = True
        self._render_timer.stop()
        self.hi.stop()
        self.lo.stop()
        self.thumbs.clear_all()
        super().closeEvent(e)
