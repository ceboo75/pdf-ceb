"""Composants d'interface réutilisables."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
from pathlib import Path

import pymupdf
from PySide6.QtCore import (QObject, QPoint, QRect, QRectF, QRunnable, QSettings, QSize, Qt, QThread,
                            QThreadPool, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from .. import core
from . import icons
from .style import ACCENT, BORDER, DANGER, MUTED

PDF_FILTER = "Documents PDF (*.pdf)"
IMG_FILTER = "Images (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp)"


# --------------------------------------------------------------------------
# Préférences, dossiers, ouverture de fichiers
# --------------------------------------------------------------------------
def settings() -> QSettings:
    return QSettings("PDF Ceb", "PDF Ceb")


def last_dir() -> str:
    d = settings().value("last_dir", "")
    if d and Path(d).exists():
        return d
    docs = Path.home() / "Documents"
    return str(docs if docs.exists() else Path.home())


def remember_dir(path):
    p = Path(path)
    settings().setValue("last_dir", str(p if p.is_dir() else p.parent))


def open_path(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def show_in_folder(path):
    path = Path(path)
    if sys.platform.startswith("win") and path.exists() and path.is_file():
        subprocess.Popen(f'explorer /select,"{os.path.normpath(str(path))}"')
    else:
        open_path(path if path.is_dir() else path.parent)


def human_size(n: int) -> str:
    for unit in ("octets", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "octets" else f"{n:,.1f} {unit}".replace(",", " ").replace(".", ",")
        n /= 1024
    return str(n)


def suggest_output(src, suffix: str, ext=".pdf") -> str:
    src = Path(src)
    return str(core._unique(src.with_name(f"{src.stem}_{suffix}{ext}")))


def ask_save_pdf(parent, suggested: str) -> str | None:
    start = suggested if Path(suggested).parent.exists() else str(Path(last_dir()) / Path(suggested).name)
    path, _ = QFileDialog.getSaveFileName(parent, "Enregistrer le PDF", start, PDF_FILTER)
    if not path:
        return None
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    remember_dir(path)
    return path


def ask_folder(parent, start: str | None = None, title="Choisir le dossier de destination") -> str | None:
    path = QFileDialog.getExistingDirectory(parent, title, start or last_dir())
    if path:
        remember_dir(path)
    return path or None


def ask_password(parent, path) -> str | None:
    """Demande le mot de passe d'un PDF protégé jusqu'à ce qu'il soit correct."""
    name = Path(path).name
    prompt = f"« {name} » est protégé.\nSaisissez son mot de passe :"
    while True:
        pw, ok = QInputDialog.getText(parent, "PDF protégé", prompt, QLineEdit.Password)
        if not ok:
            return None
        if core.check_password(path, pw):
            return pw
        prompt = f"Mot de passe incorrect pour « {name} ».\nRéessayez :"


def error_box(parent, exc, title="Une erreur est survenue"):
    if isinstance(exc, core.PdfError):
        msg = str(exc)
    else:
        msg = ("L'opération n'a pas pu aboutir.\n\n"
               f"Détail technique (à me transmettre si le problème persiste) :\n{type(exc).__name__} : {exc}")
    QMessageBox.warning(parent, title, msg)


# --------------------------------------------------------------------------
# Exécution en arrière-plan
# --------------------------------------------------------------------------
class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn, args, kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()

    def run(self):
        try:
            res = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(res)


_running: set = set()


def run_task(fn, *args, on_done=None, on_error=None, **kwargs):
    task = _Task(fn, args, kwargs)
    _running.add(task)

    def finish_ok(res):
        _running.discard(task)
        if on_done:
            on_done(res)

    def finish_err(exc):
        _running.discard(task)
        if on_error:
            on_error(exc)

    task.signals.done.connect(finish_ok)
    task.signals.failed.connect(finish_err)
    QThreadPool.globalInstance().start(task)
    return task


def wait_all_tasks(timeout_ms=60000):
    QThreadPool.globalInstance().waitForDone(timeout_ms)


# --------------------------------------------------------------------------
# Rendu des pages dans un fil dédié
# --------------------------------------------------------------------------
def pixmap_to_qimage(pix: pymupdf.Pixmap) -> QImage:
    fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


class PageRenderer(QThread):
    """Rend des pages d'un document à la demande, sans bloquer l'interface."""

    rendered = Signal(object, int, float, QImage)  # étiquette, page, échelle, image

    def __init__(self, path, password=None, data: bytes | None = None, parent=None):
        super().__init__(parent)
        self._data = data if data is not None else Path(path).read_bytes()
        self._password = password
        self._q: queue.Queue = queue.Queue()
        self._stop = False

    def request(self, tag, pno: int, scale: float):
        self._q.put((tag, pno, scale))

    def clear(self):
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def stop(self):
        self._stop = True
        self.clear()
        self._q.put(None)
        self.wait(3000)

    def run(self):
        try:
            doc = pymupdf.open(stream=self._data, filetype="pdf")
            if doc.needs_pass:
                doc.authenticate(self._password or "")
        except Exception:
            return
        while not self._stop:
            item = self._q.get()
            if item is None or self._stop:
                break
            tag, pno, scale = item
            try:
                pix = doc[pno].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                img = pixmap_to_qimage(pix)
            except Exception:
                continue
            if not self._stop:
                self.rendered.emit(tag, pno, scale, img)
        doc.close()


def render_thumbnail(path, password=None, pno=0, max_side=200) -> QImage | None:
    """Rendu synchrone d'une vignette (petits besoins ponctuels)."""
    try:
        if core.is_image(path):
            img = QImage(str(path))
            return img.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not img.isNull() else None
        doc = core.open_pdf(path, password)
        page = doc[pno]
        z = max_side / max(page.rect.width, page.rect.height)
        img = pixmap_to_qimage(page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False))
        doc.close()
        return img
    except Exception:
        return None


# --------------------------------------------------------------------------
# Zone de dépôt
# --------------------------------------------------------------------------
class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self, title: str, button_text: str, accept: str = "pdf", multiple=True, parent=None):
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.accept_kind = accept  # pdf | images | pdf+images
        self.multiple = multiple
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.addStretch(1)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("upload", ACCENT, 56))
        ic.setAlignment(Qt.AlignCenter)
        lay.addWidget(ic)
        t = QLabel(title)
        t.setObjectName("h2")
        t.setAlignment(Qt.AlignCenter)
        t.setWordWrap(True)
        lay.addWidget(t)
        self.btn = QPushButton(button_text)
        self.btn.setObjectName("big")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn)
        row.addStretch(1)
        lay.addSpacing(10)
        lay.addLayout(row)
        sub = QLabel("ou glissez-déposez vos fichiers ici")
        sub.setObjectName("muted")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        lay.addStretch(1)

    def _filter(self):
        if self.accept_kind == "images":
            return IMG_FILTER
        if self.accept_kind == "pdf+images":
            return "PDF et images (*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp)"
        return PDF_FILTER

    def browse(self):
        if self.multiple:
            paths, _ = QFileDialog.getOpenFileNames(self, "Choisir des fichiers", last_dir(), self._filter())
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier", last_dir(), self._filter())
            paths = [p] if p else []
        if paths:
            remember_dir(paths[0])
            self.files_dropped.emit(paths)

    def _ok(self, path: str) -> bool:
        if self.accept_kind == "images":
            return core.is_image(path)
        if self.accept_kind == "pdf+images":
            return core.is_pdf(path) or core.is_image(path)
        return core.is_pdf(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.setProperty("hover", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, e):
        self.setProperty("hover", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, e):
        self.dragLeaveEvent(e)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if self._ok(p)]
        if not paths:
            QMessageBox.information(self, "Format non pris en charge",
                                    "Ces fichiers ne sont pas du bon format pour cet outil.")
            return
        if not self.multiple:
            paths = paths[:1]
        remember_dir(paths[0])
        self.files_dropped.emit(paths)


def accept_file_drops(widget: QWidget, callback, kind="pdf"):
    """Permet de déposer des fichiers sur n'importe quel widget."""
    widget.setAcceptDrops(True)
    ok = {"pdf": core.is_pdf, "images": core.is_image,
          "pdf+images": lambda p: core.is_pdf(p) or core.is_image(p)}[kind]

    def enter(e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def drop(e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile() and ok(u.toLocalFile())]
        if paths:
            callback(paths)

    widget.dragEnterEvent = enter
    widget.dragMoveEvent = enter
    widget.dropEvent = drop


# --------------------------------------------------------------------------
# Grille de vignettes de pages
# --------------------------------------------------------------------------
ROLE_PAGE = Qt.UserRole + 1
ROLE_IMAGE = Qt.UserRole + 2


class ThumbDelegate(QStyledItemDelegate):
    CELL = QSize(152, 206)

    def __init__(self, grid, cell: QSize | None = None):
        super().__init__(grid)
        self.grid = grid
        self.cell = cell or self.CELL

    def sizeHint(self, option, index):
        return self.cell

    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = option.rect.adjusted(6, 6, -6, -6)
        selected = bool(option.state & QStyle.State_Selected)
        mode = self.grid.mode
        data = index.data(ROLE_PAGE) or {}
        accent = QColor(DANGER if mode == "delete" else ACCENT)
        bg = QColor("#ffffff")
        if selected:
            bg = QColor("#fff0f0") if mode == "delete" else QColor("#edf2ff")
        p.setPen(QPen(accent, 2) if selected else QPen(QColor(BORDER), 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(r), 10, 10)
        area = QRect(r.x() + 10, r.y() + 10, r.width() - 20, r.height() - 44)
        img: QImage = index.data(ROLE_IMAGE)
        rot = int(data.get("rot", 0)) % 360
        if data.get("blank"):
            w, h = data.get("width", 595), data.get("height", 842)
            s = min(area.width() / w, area.height() / h)
            rr = QRectF(0, 0, w * s, h * s)
            rr.moveCenter(QRectF(area).center())
            p.setPen(QPen(QColor("#c3cad9"), 1, Qt.DashLine))
            p.setBrush(QColor("white"))
            p.drawRect(rr)
        elif img is not None and not img.isNull():
            if rot:
                img = img.transformed(QTransform().rotate(rot), Qt.SmoothTransformation)
            s = min(area.width() / img.width(), area.height() / img.height())
            rr = QRectF(0, 0, img.width() * s, img.height() * s)
            rr.moveCenter(QRectF(area).center())
            p.setPen(QPen(QColor("#d5dae4"), 1))
            p.drawRect(rr.adjusted(-0.5, -0.5, 0.5, 0.5))
            p.drawImage(rr, img)
            if mode == "delete" and selected:
                p.fillRect(rr, QColor(224, 49, 49, 60))
        else:
            p.setPen(QColor(MUTED))
            p.drawText(area, Qt.AlignCenter, "…")
        # étiquette
        label = index.data(Qt.DisplayRole) or ""
        p.setPen(QColor("#1f2430") if not selected else accent)
        f = QFont(p.font())
        f.setPixelSize(12)
        f.setBold(selected)
        p.setFont(f)
        p.drawText(QRect(r.x(), r.bottom() - 30, r.width(), 24), Qt.AlignCenter, label)
        # badges
        if rot:
            badge = QRect(r.right() - 34, r.y() + 6, 30, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(badge, 9, 9)
            p.setPen(QColor("white"))
            f.setPixelSize(10)
            f.setBold(True)
            p.setFont(f)
            p.drawText(badge, Qt.AlignCenter, f"{rot}°")
        src_badge = data.get("badge")
        if src_badge:
            badge = QRect(r.x() + 6, r.y() + 6, 20, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(data.get("badge_color", "#868e96")))
            p.drawRoundedRect(badge, 6, 6)
            p.setPen(QColor("white"))
            f.setPixelSize(10)
            f.setBold(True)
            p.setFont(f)
            p.drawText(badge, Qt.AlignCenter, src_badge)
        if mode == "delete" and selected:
            c = QRect(r.right() - 30, r.bottom() - 62, 24, 24)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(DANGER))
            p.drawEllipse(c)
            p.drawPixmap(c.adjusted(4, 4, -4, -4), icons.pixmap("trash", "#ffffff", 16))
        p.restore()


BADGE_COLORS = ["#4263eb", "#e8590c", "#2f9e44", "#7048e8", "#c2255c", "#1098ad", "#f08c00"]


class ThumbGrid(QListWidget):
    """Grille de pages : sélection, réorganisation par glisser-déposer."""

    files_dropped = Signal(list)

    def __init__(self, mode="select", reorder=False, parent=None, cell: QSize | None = None, vertical=False):
        super().__init__(parent)
        self.mode = mode
        self.setViewMode(QListView.ListMode)
        self.setFlow(QListView.TopToBottom if vertical else QListView.LeftToRight)
        self.setWrapping(not vertical)
        self.setResizeMode(QListView.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setItemDelegate(ThumbDelegate(self, cell))
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.reorder = reorder
        if reorder:
            self.setDragDropMode(QAbstractItemView.InternalMove)
            self.setDefaultDropAction(Qt.MoveAction)
            self.setMovement(QListView.Snap)
        else:
            self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.setAcceptDrops(True)
        self._renderers: list[PageRenderer] = []
        self._items_by_key: dict = {}
        self.sources: list[tuple[str, str | None]] = []

    # -- chargement
    def add_document(self, path, password=None, badge: str | None = None):
        src_index = len(self.sources)
        self.sources.append((str(path), password))
        doc = core.open_pdf(path, password)
        n = doc.page_count
        sizes = [(p.rect.width, p.rect.height) for p in doc]
        doc.close()
        renderer = PageRenderer(path, password, parent=self)
        renderer.rendered.connect(self._on_rendered)
        self._renderers.append(renderer)
        for i in range(n):
            it = QListWidgetItem(f"{i + 1}")
            data = {"src": src_index, "page": i, "rot": 0, "width": sizes[i][0], "height": sizes[i][1]}
            if badge:
                data["badge"] = badge
                data["badge_color"] = BADGE_COLORS[src_index % len(BADGE_COLORS)]
            it.setData(ROLE_PAGE, data)
            flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
            if self.reorder:
                flags |= Qt.ItemIsDragEnabled
            it.setFlags(flags)
            self.addItem(it)
            self._items_by_key[(src_index, i)] = it
            z = 190 / max(max(sizes[i]), 1)
            renderer.request(src_index, i, z)
        renderer.start()
        return n

    def clear_all(self):
        for r in self._renderers:
            r.stop()
        self._renderers.clear()
        self._items_by_key.clear()
        self.sources.clear()
        self.clear()

    def _on_rendered(self, src_index, pno, scale, img):
        it = self._items_by_key.get((src_index, pno))
        if it is not None:
            try:
                it.setData(ROLE_IMAGE, img)
            except RuntimeError:
                pass

    def page_items(self) -> list[dict]:
        return [self.item(i).data(ROLE_PAGE) for i in range(self.count())]

    def selected_rows(self) -> list[int]:
        return sorted(self.row(it) for it in self.selectedItems())

    def relabel(self):
        for i in range(self.count()):
            it = self.item(i)
            d = it.data(ROLE_PAGE)
            if d.get("blank"):
                it.setText(f"{i + 1} · vierge")
            elif len(self.sources) > 1:
                it.setText(f"{i + 1}  (p. {d['page'] + 1})")
            else:
                it.setText(f"{d['page'] + 1}")

    def rotate_selected(self, angle: int, all_pages=False):
        items = [self.item(i) for i in range(self.count())] if all_pages else self.selectedItems()
        for it in items:
            d = dict(it.data(ROLE_PAGE))
            d["rot"] = (d.get("rot", 0) + angle) % 360
            it.setData(ROLE_PAGE, d)

    def insert_blank(self, row: int, width=595.28, height=841.89):
        it = QListWidgetItem("vierge")
        it.setData(ROLE_PAGE, {"blank": True, "width": width, "height": height, "rot": 0})
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if self.reorder:
            flags |= Qt.ItemIsDragEnabled
        it.setFlags(flags)
        self.insertItem(row, it)
        return it

    def select_pages(self, indices: list[int]):
        self.clearSelection()
        for i in indices:
            if 0 <= i < self.count():
                self.item(i).setSelected(True)

    # -- dépôt de fichiers externes
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if core.is_pdf(u.toLocalFile())]
            if paths:
                self.files_dropped.emit(paths)
            e.acceptProposedAction()
            return
        super().dropEvent(e)
        QTimer.singleShot(0, self.relabel)

    def closeEvent(self, e):
        self.clear_all()
        super().closeEvent(e)


def ranges_text(indices: list[int]) -> str:
    """[0,1,2,4] → « 1-3, 5 »."""
    if not indices:
        return ""
    idx = sorted(set(indices))
    parts, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i == prev + 1:
            prev = i
            continue
        parts.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
        start = prev = i
    parts.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
    return ", ".join(parts)


# --------------------------------------------------------------------------
# Liste de fichiers (fusion, images, compression…)
# --------------------------------------------------------------------------
class FileList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self, kind="pdf", parent=None):
        super().__init__(parent)
        self.setObjectName("fileList")
        self.kind = kind
        self.setIconSize(QSize(60, 78))
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setSpacing(1)

    def total_pages(self) -> int:
        return sum(int(self.item(i).data(Qt.UserRole + 1) or 0) for i in range(self.count()))

    def add_file(self, path, password=None, info: str = "", pages: int = 1):
        thumb = render_thumbnail(path, password, 0, 120)
        it = QListWidgetItem(f"{Path(path).name}\n{info}")
        if thumb is not None:
            canvas = QPixmap(92, 120)
            canvas.fill(Qt.transparent)
            pm = QPixmap.fromImage(thumb).scaled(92, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p = QPainter(canvas)
            p.drawPixmap((92 - pm.width()) // 2, (120 - pm.height()) // 2, pm)
            p.setPen(QPen(QColor("#d5dae4")))
            p.drawRect((92 - pm.width()) // 2, (120 - pm.height()) // 2, pm.width() - 1, pm.height() - 1)
            p.end()
            it.setIcon(canvas)
        else:
            it.setIcon(icons.icon("file", MUTED, 48))
        it.setData(Qt.UserRole, (str(path), password))
        it.setData(Qt.UserRole + 1, pages)
        it.setToolTip(str(path))
        self.addItem(it)

    def entries(self) -> list[tuple[str, str | None]]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def remove_selected(self):
        for it in self.selectedItems():
            self.takeItem(self.row(it))

    def move_selected(self, delta: int):
        rows = sorted((self.row(it) for it in self.selectedItems()), reverse=delta > 0)
        for r in rows:
            nr = r + delta
            if 0 <= nr < self.count():
                it = self.takeItem(r)
                self.insertItem(nr, it)
                it.setSelected(True)

    def sort_by_name(self):
        items = [self.takeItem(0) for _ in range(self.count())]
        items.sort(key=lambda it: Path(it.data(Qt.UserRole)[0]).name.lower())
        for it in items:
            self.addItem(it)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.files_dropped.emit(paths)
            e.acceptProposedAction()
            return
        super().dropEvent(e)


# --------------------------------------------------------------------------
# Fenêtre de résultat
# --------------------------------------------------------------------------
class ResultDialog(QDialog):
    def __init__(self, parent, title: str, message: str, files: list[str], folder: str | None = None,
                 details: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Terminé")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(10)
        top = QHBoxLayout()
        badge = QLabel()
        badge.setFixedSize(46, 46)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("background:#ebfbee; border-radius:23px;")
        badge.setPixmap(icons.pixmap("check", "#2f9e44", 26, width=2.4))
        top.addWidget(badge)
        t = QLabel(title)
        t.setObjectName("h2")
        t.setWordWrap(True)
        top.addWidget(t, 1)
        lay.addLayout(top)
        m = QLabel(message)
        m.setWordWrap(True)
        m.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(m)
        if details:
            from PySide6.QtWidgets import QPlainTextEdit
            box = QPlainTextEdit(details)
            box.setReadOnly(True)
            box.setMinimumHeight(160)
            lay.addWidget(box)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        target_folder = folder or (str(Path(files[0]).parent) if files else None)
        if target_folder:
            b = QPushButton(icons.icon("folder", "#1f2430", 18), " Ouvrir le dossier")
            b.clicked.connect(lambda: (show_in_folder(files[0] if len(files) == 1 else target_folder), self.accept()))
            row.addWidget(b)
        if len(files) == 1:
            o = QPushButton(" Ouvrir le fichier")
            o.setObjectName("primary")
            o.setIcon(icons.icon("file", "#ffffff", 18))
            o.clicked.connect(lambda: (open_path(files[0]), self.accept()))
            row.addWidget(o)
            o.setDefault(True)
        lay.addLayout(row)
