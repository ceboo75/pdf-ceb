"""Pages des outils (une par fonctionnalité)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pymupdf
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSlider, QSpinBox,
                               QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .. import core
from . import icons
from .style import ACCENT, CATEGORIES, DANGER, MUTED, soft
from .widgets import (DropZone, FileList, ResultDialog, ThumbGrid, accept_file_drops, ask_folder, ask_password,
                      ask_save_pdf, error_box, human_size, pixmap_to_qimage, ranges_text, render_thumbnail,
                      run_task, suggest_output, IMG_FILTER, PDF_FILTER, last_dir, remember_dir)


def _label(text, name=None, wrap=True):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _btn(text, icon_name=None, color="#1f2430", slot=None, obj=None):
    b = QPushButton(text)
    if icon_name:
        b.setIcon(icons.icon(icon_name, color, 18))
    if slot:
        b.clicked.connect(slot)
    if obj:
        b.setObjectName(obj)
    b.setCursor(Qt.PointingHandCursor)
    return b


def _options(parent_layout, choices, default=0):
    """Groupe de boutons radio présentés comme des cartes."""
    group = QButtonGroup(parent_layout.parentWidget())
    buttons = []
    for i, (value, text) in enumerate(choices):
        rb = QRadioButton(text)
        rb.setObjectName("option")
        rb.setProperty("value", value)
        rb.setChecked(i == default)
        group.addButton(rb, i)
        parent_layout.addWidget(rb)
        buttons.append(rb)
    return group


def _group_value(group: QButtonGroup):
    b = group.checkedButton()
    return b.property("value") if b else None


class FilePreview(QFrame):
    """Aperçu d'un fichier : vignette + informations."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("box")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.addStretch(1)
        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.thumb)
        self.name = _label("", "h2")
        self.name.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.name)
        self.info = _label("", "muted")
        self.info.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.info)
        lay.addStretch(1)

    def set_file(self, path, password=None):
        img = render_thumbnail(path, password, 0, 420)
        if img is not None:
            pm = QPixmap.fromImage(img).scaled(300, 380, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            canvas = QPixmap(pm.width() + 2, pm.height() + 2)
            canvas.fill(QColor("#d5dae4"))
            p = QPainter(canvas)
            p.drawPixmap(1, 1, pm)
            p.end()
            self.thumb.setPixmap(canvas)
        self.name.setText(Path(path).name)
        try:
            info = core.pdf_info(path, password)
            prot = " · protégé" if info["encrypted"] else ""
            self.info.setText(f"{info['pages']} page(s) · {human_size(info['size'])}{prot}")
        except Exception:
            self.info.setText("")


# --------------------------------------------------------------------------
# Page d'outil générique
# --------------------------------------------------------------------------
class ToolPage(QWidget):
    KEY = ""
    TITLE = ""
    DESC = ""
    CAT = "organiser"
    ICON = "file"
    ACCEPT = "pdf"
    MULTI = False
    ACTION = "Valider"
    DROP_TITLE = "Choisissez un fichier PDF"
    BROWSE = "Choisir un fichier PDF"
    PANEL_WIDTH = 340

    def __init__(self, main):
        super().__init__()
        self.setObjectName("page")
        self.main = main
        self.entries: list[tuple[str, str | None]] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)
        head = QHBoxLayout()
        color = CATEGORIES[self.CAT][1]
        badge = QLabel()
        badge.setFixedSize(46, 46)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"background: {soft(color)}; border-radius: 12px;")
        badge.setPixmap(icons.pixmap(self.ICON, color, 26))
        head.addWidget(badge)
        tl = QVBoxLayout()
        tl.setSpacing(0)
        tl.addWidget(_label(self.TITLE, "h1", wrap=False))
        tl.addWidget(_label(self.DESC, "muted"))
        head.addLayout(tl, 1)
        self.reset_btn = _btn(" Recommencer", "undo", slot=self.reset)
        self.reset_btn.setVisible(False)
        head.addWidget(self.reset_btn, 0, Qt.AlignTop)
        root.addLayout(head)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.drop = DropZone(self.DROP_TITLE, self.BROWSE, self.ACCEPT, self.MULTI)
        self.drop.files_dropped.connect(self.load_files)
        self.stack.addWidget(self.drop)

        work = QWidget()
        wl = QHBoxLayout(work)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(16)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)
        wl.addWidget(self.content, 1)
        self.panel = QFrame()
        self.panel.setObjectName("box")
        self.panel.setFixedWidth(self.PANEL_WIDTH)
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(18, 18, 18, 18)
        pl.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.opts = QVBoxLayout(inner)
        self.opts.setContentsMargins(0, 0, 4, 0)
        self.opts.setSpacing(8)
        scroll.setWidget(inner)
        pl.addWidget(scroll, 1)
        self.status = _label("", "hint")
        pl.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setVisible(False)
        pl.addWidget(self.progress)
        self.run_btn = _btn(self.ACTION, slot=self.run, obj="primary")
        self.run_btn.setMinimumHeight(48)
        pl.addWidget(self.run_btn)
        wl.addWidget(self.panel)
        self.stack.addWidget(work)
        self.build_content(self.content_layout)
        self.build_options(self.opts)
        self.opts.addStretch(1)
        accept_file_drops(self.content, self.load_files, self.ACCEPT)

    # à surcharger
    def build_content(self, lay: QVBoxLayout):
        self.preview = FilePreview()
        lay.addWidget(self.preview, 1)

    def build_options(self, lay: QVBoxLayout):
        pass

    def on_files(self, entries):
        """Appelée avec la liste complète des fichiers chargés."""
        if hasattr(self, "preview") and isinstance(self.preview, FilePreview) and entries:
            self.preview.set_file(*entries[0])

    def clear(self):
        pass

    def task(self):
        """Renvoie (fonction, args, kwargs, callback_succès) ou None."""
        return None

    # mécanique commune
    def _prepare_entries(self, paths):
        out = []
        for p in paths:
            pw = None
            if core.is_pdf(p) and core.needs_password(p):
                pw = ask_password(self, p)
                if pw is None:
                    continue
            if core.is_pdf(p):
                try:
                    core.open_pdf(p, pw).close()
                except Exception as exc:  # noqa: BLE001
                    error_box(self, exc, "Fichier illisible")
                    continue
            out.append((str(p), pw))
        return out

    def load_files(self, paths):
        new = self._prepare_entries(paths)
        if not new:
            return
        if self.MULTI:
            self.entries.extend(new)
        else:
            self.clear()
            self.entries = new[:1]
        self.stack.setCurrentIndex(1)
        self.reset_btn.setVisible(True)
        self.status.setText("")
        try:
            self.on_files(new if self.MULTI else self.entries)
        except Exception as exc:  # noqa: BLE001
            error_box(self, exc)
            self.reset()

    def reset(self):
        self.entries = []
        self.clear()
        self.status.setText("")
        self.stack.setCurrentIndex(0)
        self.reset_btn.setVisible(False)

    def set_busy(self, busy: bool, text=""):
        self.progress.setVisible(busy)
        self.run_btn.setEnabled(not busy)
        self.status.setText(text)

    def run(self):
        try:
            spec = self.task()
        except core.PdfError as exc:
            error_box(self, exc, "Vérifiez les options")
            return
        if not spec:
            return
        fn, args, kwargs, on_ok = spec
        self.set_busy(True, "Traitement en cours…")

        def done(res):
            self.set_busy(False)
            try:
                on_ok(res)
            except Exception as exc:  # noqa: BLE001
                error_box(self, exc)

        def fail(exc):
            self.set_busy(False)
            error_box(self, exc)

        run_task(fn, *args, on_done=done, on_error=fail, **kwargs)

    def done_dialog(self, title, message, files, folder=None, details=None):
        ResultDialog(self, title, message, files, folder, details).exec()

    @property
    def src(self):
        return self.entries[0][0]

    @property
    def pw(self):
        return self.entries[0][1]


# --------------------------------------------------------------------------
# Outils avec liste de fichiers
# --------------------------------------------------------------------------
class FileListTool(ToolPage):
    MULTI = True
    LIST_KIND = "pdf"

    def build_content(self, lay):
        self.list = FileList(self.LIST_KIND)
        self.list.files_dropped.connect(self.load_files)
        self.list.model().rowsRemoved.connect(lambda *_: self.update_info())
        self.list.model().rowsInserted.connect(lambda *_: self.update_info())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(_btn(" Ajouter des fichiers", "plus", slot=self.drop.browse))
        row.addWidget(_btn(" Retirer", "close", slot=self._remove))
        row.addStretch(1)
        up = _btn("", "up", slot=lambda: self.list.move_selected(-1))
        up.setToolTip("Monter")
        down = _btn("", "down", slot=lambda: self.list.move_selected(1))
        down.setToolTip("Descendre")
        row.addWidget(up)
        row.addWidget(down)
        row.addWidget(_btn(" Trier par nom", "sort", slot=self.list.sort_by_name))
        lay.addLayout(row)
        lay.addWidget(_label("Astuce : faites glisser les fichiers dans la liste pour changer leur ordre.", "hint"))

    def on_files(self, entries):
        for path, pw in entries:
            info, pages = "", 1
            try:
                if core.is_pdf(path):
                    i = core.pdf_info(path, pw)
                    pages = i["pages"]
                    info = f"{pages} page(s) · {human_size(i['size'])}"
                else:
                    info = f"Image · {human_size(Path(path).stat().st_size)}"
            except Exception:
                pass
            self.list.add_file(path, pw, info, pages)
        self.update_info()

    def _remove(self):
        self.list.remove_selected()
        if self.list.count() == 0:
            self.reset()

    def clear(self):
        self.list.clear()

    def update_info(self):
        self.entries = self.list.entries()

    def files(self):
        return self.list.entries()


class MergeTool(FileListTool):
    KEY, TITLE, CAT, ICON = "merge", "Fusionner des PDF", "organiser", "merge"
    DESC = "Réunissez plusieurs PDF (et images) en un seul document, dans l'ordre de votre choix."
    ACCEPT = LIST_KIND = "pdf+images"
    ACTION = "Fusionner"
    DROP_TITLE = "Choisissez les PDF à fusionner"
    BROWSE = "Choisir des fichiers"

    def build_options(self, lay):
        lay.addWidget(_label("Options", "section"))
        self.bookmarks = QCheckBox("Créer un signet par fichier")
        self.bookmarks.setChecked(True)
        lay.addWidget(self.bookmarks)
        lay.addWidget(_label("Les signets permettent de retrouver chaque document d'origine dans le PDF fusionné.",
                             "hint"))
        self.summary = _label("", "muted")
        lay.addWidget(self.summary)

    def update_info(self):
        super().update_info()
        files = self.files()
        pages = self.list.total_pages()
        self.summary.setText(f"{len(files)} fichier(s) · {pages} page(s) au total")

    def task(self):
        files = self.files()
        if len(files) < 2:
            raise core.PdfError("Ajoutez au moins deux fichiers à fusionner.")
        out = ask_save_pdf(self, str(core._unique(Path(files[0][0]).with_name("fusion.pdf"))))
        if not out:
            return None
        return (core.merge, (files, out), {"bookmarks": self.bookmarks.isChecked()},
                lambda res: self.done_dialog("Vos PDF ont été fusionnés",
                                             f"{len(files)} fichiers réunis dans « {Path(res).name} ».", [res]))


class CompressTool(FileListTool):
    KEY, TITLE, CAT, ICON = "compress", "Compresser un PDF", "optimiser", "compress"
    DESC = "Réduisez la taille de vos PDF en optimisant les images et la structure du fichier."
    ACTION = "Compresser"
    DROP_TITLE = "Choisissez le ou les PDF à compresser"
    BROWSE = "Choisir des fichiers PDF"

    def build_options(self, lay):
        lay.addWidget(_label("Niveau de compression", "section"))
        self.level = _options(lay, [
            ("faible", "Faible — qualité maximale\nNettoie et recompresse sans toucher aux images"),
            ("recommandée", "Recommandée — bon compromis\nImages ramenées à 150 dpi"),
            ("forte", "Forte — taille minimale\nImages à 96 dpi, qualité réduite"),
        ], default=1)

    def task(self):
        files = self.files()
        level = _group_value(self.level)
        if len(files) == 1:
            out = ask_save_pdf(self, suggest_output(files[0][0], "compressé"))
            if not out:
                return None

            def ok(res):
                before, after = res
                gain = (1 - after / before) * 100 if before else 0
                msg = (f"Taille réduite de {gain:.0f} % : {human_size(before)} → {human_size(after)}." if after < before
                       else "Ce PDF était déjà optimisé : le fichier enregistré est identique à l'original.")
                self.done_dialog("Compression terminée", msg, [out])
            return core.compress, (files[0][0], files[0][1], out, level), {}, ok
        folder = ask_folder(self, str(Path(files[0][0]).parent))
        if not folder:
            return None

        def batch():
            res = []
            for p, pw in files:
                o = core._unique(Path(folder) / f"{Path(p).stem}_compressé.pdf")
                b, a = core.compress(p, pw, o, level)
                res.append((str(o), b, a))
            return res

        def ok(res):
            tb, ta = sum(r[1] for r in res), sum(r[2] for r in res)
            det = "\n".join(f"{Path(o).name} : {human_size(b)} → {human_size(a)}" for o, b, a in res)
            self.done_dialog("Compression terminée",
                             f"{len(res)} fichiers compressés : {human_size(tb)} → {human_size(ta)}.",
                             [r[0] for r in res], folder, det)
        return batch, (), {}, ok


class ImagesToPdfTool(FileListTool):
    KEY, TITLE, CAT, ICON = "img2pdf", "Images en PDF", "convertir", "img2pdf"
    DESC = "Transformez des photos et images (JPG, PNG, TIFF…) en document PDF."
    ACCEPT = LIST_KIND = "images"
    ACTION = "Convertir en PDF"
    DROP_TITLE = "Choisissez les images à convertir"
    BROWSE = "Choisir des images"

    def build_options(self, lay):
        lay.addWidget(_label("Format de page", "section"))
        self.size = QComboBox()
        for k in ["A4", "A3", "A5", "Lettre US"]:
            self.size.addItem(k, k)
        self.size.addItem("Taille de l'image", "image")
        lay.addWidget(self.size)
        lay.addWidget(_label("Orientation", "section"))
        self.orient = QComboBox()
        self.orient.addItem("Automatique (selon l'image)", "auto")
        self.orient.addItem("Portrait", "portrait")
        self.orient.addItem("Paysage", "paysage")
        lay.addWidget(self.orient)
        lay.addWidget(_label("Marges", "section"))
        self.margin = QComboBox()
        self.margin.addItem("Aucune", 0)
        self.margin.addItem("Petites (1 cm)", 10)
        self.margin.addItem("Grandes (2 cm)", 20)
        lay.addWidget(self.margin)
        lay.addWidget(_label("Résultat", "section"))
        self.mode = _options(lay, [("one", "Un seul PDF"), ("many", "Un PDF par image")])
        self.size.currentIndexChanged.connect(lambda: self.orient.setEnabled(self.size.currentData() != "image"))

    def task(self):
        imgs = [p for p, _ in self.files()]
        kw = dict(page_size=self.size.currentData(), orientation=self.orient.currentData(),
                  margin_mm=float(self.margin.currentData()))
        if _group_value(self.mode) == "one" or len(imgs) == 1:
            out = ask_save_pdf(self, suggest_output(imgs[0], "converti") if len(imgs) == 1 else
                               str(core._unique(Path(imgs[0]).with_name("images.pdf"))))
            if not out:
                return None
            return core.images_to_pdf, (imgs, out), kw, lambda res: self.done_dialog(
                "Votre PDF est prêt", f"{len(imgs)} image(s) converties dans « {Path(res).name} ».", [res])
        folder = ask_folder(self, str(Path(imgs[0]).parent))
        if not folder:
            return None
        return core.images_to_pdfs, (imgs, folder), kw, lambda res: self.done_dialog(
            "Conversion terminée", f"{len(res)} PDF créés.", res, folder)


# --------------------------------------------------------------------------
# Outils avec grille de pages
# --------------------------------------------------------------------------
class GridTool(ToolPage):
    GRID_MODE = "select"
    REORDER = False
    SHOW_RANGE = True
    RANGE_LABEL = "Pages sélectionnées"

    def build_content(self, lay):
        self.grid = ThumbGrid(self.GRID_MODE, self.REORDER)
        self.grid.itemSelectionChanged.connect(self._sel_changed)
        if not self.REORDER:
            self.grid.files_dropped.connect(self.load_files)
        lay.addWidget(self.grid, 1)
        self.grid_hint = _label("Cliquez sur les pages pour les sélectionner (Ctrl ou Maj pour en choisir plusieurs).",
                                "hint")
        lay.addWidget(self.grid_hint)

    def add_range_field(self, lay):
        lay.addWidget(_label(self.RANGE_LABEL, "section"))
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText("ex. : 1-3, 5, 8-")
        self.range_edit.editingFinished.connect(self._range_typed)
        lay.addWidget(self.range_edit)
        row = QHBoxLayout()
        row.addWidget(_btn("Tout sélectionner", slot=lambda: self.grid.selectAll()))
        row.addWidget(_btn("Aucune", slot=lambda: self.grid.clearSelection()))
        lay.addLayout(row)
        self.count_label = _label("", "muted")
        lay.addWidget(self.count_label)

    def _sel_changed(self):
        if hasattr(self, "range_edit"):
            rows = self.grid.selected_rows()
            self.range_edit.blockSignals(True)
            self.range_edit.setText(ranges_text(rows))
            self.range_edit.blockSignals(False)
            self.count_label.setText(self.count_text(len(rows)))

    def count_text(self, n):
        return f"{n} page(s) sélectionnée(s) sur {self.grid.count()}"

    def _range_typed(self):
        try:
            idx = core.parse_pages(self.range_edit.text(), self.grid.count()) if self.range_edit.text().strip() else []
        except core.PdfError as exc:
            self.count_label.setText(str(exc))
            return
        self.grid.blockSignals(True)
        self.grid.select_pages(idx)
        self.grid.blockSignals(False)
        self._sel_changed()

    def on_files(self, entries):
        self.grid.clear_all()
        self.grid.add_document(*entries[0])
        self.grid.relabel()
        self._sel_changed()

    def clear(self):
        self.grid.clear_all()


class SplitTool(GridTool):
    KEY, TITLE, CAT, ICON = "split", "Diviser un PDF", "organiser", "split"
    DESC = "Séparez un PDF en plusieurs fichiers : par plages de pages, toutes les N pages ou page par page."
    ACTION = "Diviser"

    def build_options(self, lay):
        lay.addWidget(_label("Mode de division", "section"))
        self.mode = _options(lay, [("ranges", "Par plages personnalisées"), ("every", "Toutes les N pages"),
                                   ("each", "Une page par fichier")])
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText("ex. : 1-3, 4-6, 7")
        lay.addWidget(_label("Plages (une par fichier)", "section"))
        lay.addWidget(self.ranges)
        use = _btn("Créer les plages depuis la sélection", slot=self._from_selection)
        lay.addWidget(use)
        lay.addWidget(_label("Chaque plage séparée par une virgule donne un fichier.", "hint"))
        lay.addWidget(_label("Nombre de pages par fichier", "section"))
        self.every = QSpinBox()
        self.every.setRange(1, 10000)
        self.every.setValue(2)
        lay.addWidget(self.every)
        self.mode.idToggled.connect(lambda *_: self._update())
        self._update()

    def _update(self):
        m = _group_value(self.mode)
        self.ranges.setEnabled(m == "ranges")
        self.every.setEnabled(m == "every")

    def _from_selection(self):
        rows = self.grid.selected_rows()
        if rows:
            self.ranges.setText(ranges_text(rows))

    def task(self):
        n = self.grid.count()
        m = _group_value(self.mode)
        if m == "ranges":
            groups = core.parse_groups(self.ranges.text(), n)
        elif m == "every":
            k = self.every.value()
            groups = [list(range(i, min(i + k, n))) for i in range(0, n, k)]
        else:
            groups = [[i] for i in range(n)]
        folder = ask_folder(self, str(Path(self.src).parent))
        if not folder:
            return None
        target = core._unique(Path(folder) / f"{Path(self.src).stem}_divisé")
        return core.split_groups, (self.src, self.pw, groups, target), {}, lambda res: self.done_dialog(
            "Division terminée", f"{len(res)} fichier(s) créé(s) dans le dossier « {target.name} ».", res, str(target))


class DeleteTool(GridTool):
    KEY, TITLE, CAT, ICON = "delete", "Supprimer des pages", "organiser", "delete"
    DESC = "Retirez les pages inutiles de votre PDF."
    GRID_MODE = "delete"
    ACTION = "Supprimer les pages"
    RANGE_LABEL = "Pages à supprimer"

    def build_options(self, lay):
        self.add_range_field(lay)

    def count_text(self, n):
        return f"{n} page(s) seront supprimées · {self.grid.count() - n} restante(s)"

    def task(self):
        rows = self.grid.selected_rows()
        if not rows:
            raise core.PdfError("Sélectionnez les pages à supprimer.")
        out = ask_save_pdf(self, suggest_output(self.src, "pages_supprimées"))
        if not out:
            return None
        return core.delete_pages, (self.src, self.pw, rows, out), {}, lambda res: self.done_dialog(
            "Pages supprimées", f"{len(rows)} page(s) retirée(s).", [res])


class ExtractTool(GridTool):
    KEY, TITLE, CAT, ICON = "extract", "Extraire des pages", "organiser", "extract"
    DESC = "Récupérez certaines pages dans un nouveau PDF."
    ACTION = "Extraire"
    RANGE_LABEL = "Pages à extraire"

    def build_options(self, lay):
        self.add_range_field(lay)
        lay.addWidget(_label("Résultat", "section"))
        self.mode = _options(lay, [("one", "Un seul PDF"), ("many", "Un PDF par page")])

    def task(self):
        rows = core.parse_pages(self.range_edit.text(), self.grid.count()) if self.range_edit.text().strip() else []
        if not rows:
            raise core.PdfError("Sélectionnez les pages à extraire.")
        if _group_value(self.mode) == "one":
            out = ask_save_pdf(self, suggest_output(self.src, "extrait"))
            if not out:
                return None
            return core.extract_pages, (self.src, self.pw, rows, out), {}, lambda res: self.done_dialog(
                "Extraction terminée", f"{len(rows)} page(s) extraite(s).", [res])
        folder = ask_folder(self, str(Path(self.src).parent))
        if not folder:
            return None
        return core.split_groups, (self.src, self.pw, [[r] for r in rows], folder), {}, lambda res: self.done_dialog(
            "Extraction terminée", f"{len(res)} fichier(s) créé(s).", res, folder)


class OrganizeTool(GridTool):
    KEY, TITLE, CAT, ICON = "organize", "Organiser les pages", "organiser", "organize"
    DESC = "Réordonnez, faites pivoter, supprimez ou ajoutez des pages — y compris depuis d'autres PDF."
    REORDER = True
    ACTION = "Enregistrer le PDF"

    def build_content(self, lay):
        bar = QHBoxLayout()
        for text, ic, fn, tip in [
            ("", "rotate_left", lambda: self.grid.rotate_selected(-90), "Pivoter à gauche"),
            ("", "rotate", lambda: self.grid.rotate_selected(90), "Pivoter à droite"),
            (" Supprimer", "trash", self._delete, "Supprimer les pages sélectionnées"),
            (" Page vierge", "blank", self._blank, "Insérer une page vierge après la sélection"),
            (" Ajouter un PDF", "plus", self._add_pdf, "Ajouter les pages d'un autre PDF"),
            (" Inverser", "reverse", self._reverse, "Inverser l'ordre des pages"),
            ("", "left", lambda: self._move(-1), "Déplacer la sélection vers le début"),
            ("", "right", lambda: self._move(1), "Déplacer la sélection vers la fin"),
        ]:
            b = _btn(text, ic, slot=fn)
            b.setToolTip(tip)
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        super().build_content(lay)
        self.grid_hint.setText("Faites glisser les pages pour changer leur ordre. Ctrl ou Maj pour sélectionner "
                               "plusieurs pages. Vous pouvez aussi déposer d'autres PDF ici.")
        self.grid.files_dropped.connect(self._add_paths)
        self.grid.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self.grid.relabel))

    def build_options(self, lay):
        lay.addWidget(_label("Document final", "section"))
        self.info = _label("", "muted")
        lay.addWidget(self.info)
        lay.addWidget(_label("Les pages apparaissent dans l'ordre de la grille. Les pastilles de couleur indiquent "
                             "le fichier d'origine lorsque plusieurs PDF sont combinés.", "hint"))
        self.files_label = _label("", "hint")
        lay.addWidget(self.files_label)

    def _refresh(self):
        self.grid.relabel()
        self.info.setText(f"{self.grid.count()} page(s)")
        self.files_label.setText("\n".join(f"{chr(65 + i)} : {Path(p).name}" for i, (p, _) in enumerate(self.grid.sources))
                                 if len(self.grid.sources) > 1 else "")

    def on_files(self, entries):
        self.grid.clear_all()
        self.grid.add_document(*entries[0], badge=None)
        self._refresh()

    def _add_paths(self, paths):
        for p, pw in self._prepare_entries(paths):
            if len(self.grid.sources) == 1:
                # on ajoute une pastille au premier document pour distinguer les sources
                for i in range(self.grid.count()):
                    it = self.grid.item(i)
                    d = dict(it.data(Qt.UserRole + 1))
                    if not d.get("blank"):
                        d["badge"], d["badge_color"] = "A", "#4263eb"
                        it.setData(Qt.UserRole + 1, d)
            self.grid.add_document(p, pw, badge=chr(65 + len(self.grid.sources)))
        self._refresh()

    def _add_pdf(self):
        from PySide6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(self, "Ajouter un PDF", last_dir(), PDF_FILTER)
        if paths:
            remember_dir(paths[0])
            self._add_paths(paths)

    def _delete(self):
        for it in self.grid.selectedItems():
            self.grid.takeItem(self.grid.row(it))
        self._refresh()

    def _blank(self):
        rows = self.grid.selected_rows()
        row = (rows[-1] + 1) if rows else self.grid.count()
        ref = self.grid.item(row - 1).data(Qt.UserRole + 1) if row > 0 else None
        w, h = (ref.get("width", 595.28), ref.get("height", 841.89)) if ref else (595.28, 841.89)
        it = self.grid.insert_blank(row, w, h)
        self.grid.clearSelection()
        it.setSelected(True)
        self._refresh()

    def _move(self, delta):
        rows = sorted(self.grid.selected_rows(), reverse=delta > 0)
        if not rows or (delta < 0 and rows[-1] == 0) or (delta > 0 and rows[-1] == self.grid.count() - 1):
            return
        moved = []
        for r in rows:
            it = self.grid.takeItem(r)
            self.grid.insertItem(r + delta, it)
            moved.append(it)
        self.grid.clearSelection()
        for it in moved:
            it.setSelected(True)
        self.grid.scrollToItem(moved[0])
        self._refresh()

    def _reverse(self):
        items = [self.grid.takeItem(0) for _ in range(self.grid.count())]
        for it in reversed(items):
            self.grid.addItem(it)
        self._refresh()

    def task(self):
        items = self.grid.page_items()
        if not items:
            raise core.PdfError("Le document ne contient plus aucune page.")
        out = ask_save_pdf(self, suggest_output(self.src, "organisé"))
        if not out:
            return None
        return core.organize, (list(self.grid.sources), items, out), {}, lambda res: self.done_dialog(
            "Votre PDF est prêt", f"Document de {len(items)} page(s) enregistré.", [res])


class RotateTool(GridTool):
    KEY, TITLE, CAT, ICON = "rotate", "Faire pivoter", "modifier", "rotate"
    DESC = "Faites pivoter certaines pages ou tout le document."
    ACTION = "Enregistrer"

    def build_options(self, lay):
        lay.addWidget(_label("Pages sélectionnées", "section"))
        row = QHBoxLayout()
        row.addWidget(_btn(" Gauche", "rotate_left", slot=lambda: self.grid.rotate_selected(-90)))
        row.addWidget(_btn(" Droite", "rotate", slot=lambda: self.grid.rotate_selected(90)))
        lay.addLayout(row)
        lay.addWidget(_label("Toutes les pages", "section"))
        row = QHBoxLayout()
        row.addWidget(_btn(" Gauche", "rotate_left", slot=lambda: self.grid.rotate_selected(-90, True)))
        row.addWidget(_btn(" Droite", "rotate", slot=lambda: self.grid.rotate_selected(90, True)))
        lay.addLayout(row)
        lay.addWidget(_label("L'angle appliqué s'affiche sur chaque vignette.", "hint"))

    def task(self):
        rot = {d["page"]: d["rot"] for d in self.grid.page_items() if d.get("rot")}
        if not rot:
            raise core.PdfError("Aucune page n'a été pivotée.")
        out = ask_save_pdf(self, suggest_output(self.src, "pivoté"))
        if not out:
            return None
        return core.rotate_pages, (self.src, self.pw, rot, out), {}, lambda res: self.done_dialog(
            "Votre PDF est prêt", f"{len(rot)} page(s) pivotée(s).", [res])


class PdfToImagesTool(GridTool):
    KEY, TITLE, CAT, ICON = "pdf2img", "PDF en images", "convertir", "pdf2img"
    DESC = "Convertissez chaque page en image JPG ou PNG, ou récupérez les images contenues dans le PDF."
    ACTION = "Convertir"
    RANGE_LABEL = "Pages (laisser vide = toutes)"

    def build_options(self, lay):
        lay.addWidget(_label("Mode", "section"))
        self.mode = _options(lay, [("pages", "Convertir les pages en images"),
                                   ("extract", "Extraire les images contenues")])
        lay.addWidget(_label("Format", "section"))
        self.fmt = QComboBox()
        self.fmt.addItem("JPG (photos, fichiers légers)", "jpg")
        self.fmt.addItem("PNG (sans perte, texte net)", "png")
        lay.addWidget(self.fmt)
        lay.addWidget(_label("Qualité", "section"))
        self.dpi = QComboBox()
        self.dpi.addItem("Normale — 150 dpi", 150)
        self.dpi.addItem("Haute — 300 dpi", 300)
        self.dpi.addItem("Écran — 96 dpi", 96)
        lay.addWidget(self.dpi)
        self.add_range_field(lay)
        self.mode.idToggled.connect(lambda *_: self._upd())

    def _upd(self):
        on = _group_value(self.mode) == "pages"
        for w in (self.fmt, self.dpi, self.range_edit):
            w.setEnabled(on)

    def task(self):
        folder = ask_folder(self, str(Path(self.src).parent))
        if not folder:
            return None
        target = core._unique(Path(folder) / f"{Path(self.src).stem}_images")
        if _group_value(self.mode) == "extract":
            def ok(res):
                if not res:
                    QMessageBox.information(self, "Aucune image", "Ce PDF ne contient pas d'image exploitable.")
                    return
                self.done_dialog("Images extraites", f"{len(res)} image(s) enregistrée(s) dans « {target.name} ».",
                                 res, str(target))
            return core.extract_images, (self.src, self.pw, target), {}, ok
        pages = self.range_edit.text().strip() or None
        return core.pdf_to_images, (self.src, self.pw, target, self.fmt.currentData(), self.dpi.currentData()), \
            {"pages": pages}, lambda res: self.done_dialog(
                "Conversion terminée", f"{len(res)} image(s) créée(s) dans « {target.name} ».", res, str(target))


# --------------------------------------------------------------------------
# Outils avec aperçu en direct
# --------------------------------------------------------------------------
class LivePreview(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 360)
        self.setObjectName("box")
        self.setStyleSheet("QLabel#box { background: #e9ecf2; border: 1px solid #e1e5ee; border-radius: 10px; }")
        self._img: QImage | None = None

    def set_image(self, img: QImage | None):
        self._img = img
        self._refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self):
        if self._img is None:
            self.clear()
            return
        pm = QPixmap.fromImage(self._img).scaled(self.width() - 30, self.height() - 30, Qt.KeepAspectRatio,
                                                 Qt.SmoothTransformation)
        self.setPixmap(pm)


class PreviewTool(ToolPage):
    """Outil appliqué au PDF entier, avec aperçu de la première page."""

    def build_content(self, lay):
        self.live = LivePreview()
        lay.addWidget(self.live, 1)
        self.preview_note = _label("Aperçu sur la première page concernée", "hint")
        self.preview_note.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.preview_note)
        self._tmp = Path(tempfile.mkdtemp(prefix="pdfceb_prev_"))
        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self._render_preview)

    def on_files(self, entries):
        path, pw = entries[0]
        doc = core.open_pdf(path, pw)
        self.page_count = doc.page_count
        doc.close()
        self.sample = self._tmp / "sample.pdf"
        core.extract_pages(path, pw, [0], self.sample)
        self.schedule()

    def schedule(self, *_):
        if self.entries:
            self._timer.start()

    def preview_call(self, src, out):
        """À surcharger : applique l'opération à l'échantillon."""
        raise NotImplementedError

    def _render_preview(self):
        try:
            out = self._tmp / "preview.pdf"
            self.preview_call(str(self.sample), str(out))
            with pymupdf.open(out) as d:
                page = d[0]
                z = 700 / max(page.rect.width, page.rect.height)
                self.live.set_image(pixmap_to_qimage(page.get_pixmap(matrix=pymupdf.Matrix(z, z))))
            self.status.setText("")
        except core.PdfError as exc:
            self.status.setText(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Aperçu indisponible : {exc}")


class ColorPick(QPushButton):
    changed = Signal()

    def __init__(self, color="#000000"):
        super().__init__()
        self.set_color(color)
        self.clicked.connect(self._choose)

    def set_color(self, c):
        self._c = c
        self.setText(f"  {c.upper()}")
        pm = QPixmap(16, 16)
        pm.fill(QColor(c))
        self.setIcon(pm)

    def color(self):
        return self._c

    def _choose(self):
        c = QColorDialog.getColor(QColor(self._c), self, "Couleur")
        if c.isValid():
            self.set_color(c.name())
            self.changed.emit()


class NumbersTool(PreviewTool):
    KEY, TITLE, CAT, ICON = "numbers", "Numéroter les pages", "modifier", "numbers"
    DESC = "Ajoutez des numéros de page, avec la position et le format de votre choix."
    ACTION = "Numéroter"

    def build_options(self, lay):
        lay.addWidget(_label("Position", "section"))
        grid = QGridLayout()
        self.pos_group = QButtonGroup(self)
        positions = [("haut-gauche", 0, 0), ("haut-centre", 0, 1), ("haut-droite", 0, 2),
                     ("bas-gauche", 1, 0), ("bas-centre", 1, 1), ("bas-droite", 1, 2)]
        for i, (key, r, c) in enumerate(positions):
            b = QToolButton()
            b.setCheckable(True)
            b.setFixedSize(QSize(62, 34))
            b.setText({"gauche": "◧", "centre": "▣", "droite": "◨"}[key.split("-")[1]])
            b.setToolTip(key.replace("-", " "))
            b.setProperty("value", key)
            b.setStyleSheet("QToolButton { border: 1px solid #ccd2de; border-radius: 6px; background: white; "
                            "font-size: 16px; } QToolButton:checked { border: 2px solid %s; background: #edf2ff; }"
                            % ACCENT)
            self.pos_group.addButton(b, i)
            grid.addWidget(b, r, c)
            if key == "bas-centre":
                b.setChecked(True)
        lay.addWidget(_label("haut", "hint"))
        lay.addLayout(grid)
        lay.addWidget(_label("bas", "hint"))
        self.pos_group.idToggled.connect(self.schedule)
        lay.addWidget(_label("Format", "section"))
        self.fmt = QComboBox()
        self.fmt.setEditable(True)
        for f in ["{n}", "Page {n}", "Page {n} sur {total}", "{n} / {total}", "- {n} -"]:
            self.fmt.addItem(f)
        self.fmt.currentTextChanged.connect(self.schedule)
        lay.addWidget(self.fmt)
        lay.addWidget(_label("{n} = numéro de la page, {total} = nombre total.", "hint"))
        form = QFormLayout()
        self.first = QSpinBox()
        self.first.setRange(0, 99999)
        self.first.setValue(1)
        self.first.valueChanged.connect(self.schedule)
        form.addRow("Premier numéro", self.first)
        self.pages = QLineEdit()
        self.pages.setPlaceholderText("toutes (ex. : 2- pour sauter la 1re)")
        form.addRow("Pages", self.pages)
        self.size = QSpinBox()
        self.size.setRange(6, 48)
        self.size.setValue(11)
        self.size.valueChanged.connect(self.schedule)
        form.addRow("Taille", self.size)
        self.margin = QSpinBox()
        self.margin.setRange(3, 60)
        self.margin.setValue(10)
        self.margin.setSuffix(" mm")
        self.margin.valueChanged.connect(self.schedule)
        form.addRow("Marge", self.margin)
        self.color = ColorPick("#000000")
        self.color.changed.connect(self.schedule)
        form.addRow("Couleur", self.color)
        self.bold = QCheckBox("Gras")
        self.bold.toggled.connect(self.schedule)
        form.addRow("", self.bold)
        lay.addLayout(form)

    def _kw(self):
        b = self.pos_group.checkedButton()
        return dict(position=b.property("value") if b else "bas-centre", fmt=self.fmt.currentText() or "{n}",
                    first_number=self.first.value(), font_size=self.size.value(), margin_mm=self.margin.value(),
                    color=self.color.color(), bold=self.bold.isChecked())

    def preview_call(self, src, out):
        core.add_page_numbers(src, None, out, total=self.first.value() + self.page_count - 1, **self._kw())

    def task(self):
        pages = self.pages.text().strip() or None
        if pages:
            core.parse_pages(pages, self.page_count)
        out = ask_save_pdf(self, suggest_output(self.src, "numéroté"))
        if not out:
            return None
        return core.add_page_numbers, (self.src, self.pw, out), {**self._kw(), "pages": pages}, \
            lambda res: self.done_dialog("Votre PDF est prêt", "La numérotation a été ajoutée.", [res])


class WatermarkTool(PreviewTool):
    KEY, TITLE, CAT, ICON = "watermark", "Ajouter un filigrane", "modifier", "watermark"
    DESC = "Apposez un texte (CONFIDENTIEL, BROUILLON…) ou une image en filigrane."
    ACTION = "Ajouter le filigrane"

    def build_options(self, lay):
        self.tabs = QTabWidget()
        # texte
        t = QWidget()
        f = QFormLayout(t)
        self.text = QLineEdit("CONFIDENTIEL")
        self.text.textChanged.connect(self.schedule)
        f.addRow("Texte", self.text)
        self.tsize = QSpinBox()
        self.tsize.setRange(8, 200)
        self.tsize.setValue(60)
        self.tsize.valueChanged.connect(self.schedule)
        f.addRow("Taille", self.tsize)
        self.tcolor = ColorPick("#c92a2a")
        self.tcolor.changed.connect(self.schedule)
        f.addRow("Couleur", self.tcolor)
        self.angle = QComboBox()
        for label, a in [("Diagonale ↗", 45), ("Horizontal", 0), ("Diagonale ↘", -45), ("Vertical", 90)]:
            self.angle.addItem(label, a)
        self.angle.currentIndexChanged.connect(self.schedule)
        f.addRow("Inclinaison", self.angle)
        self.tbold = QCheckBox("Gras")
        self.tbold.setChecked(True)
        self.tbold.toggled.connect(self.schedule)
        f.addRow("", self.tbold)
        self.tabs.addTab(t, "Texte")
        # image
        w = QWidget()
        f2 = QFormLayout(w)
        self.img_path = None
        self.img_btn = _btn("Choisir une image…", "image", slot=self._choose_img)
        f2.addRow(self.img_btn)
        self.scale = QSlider(Qt.Horizontal)
        self.scale.setRange(5, 100)
        self.scale.setValue(45)
        self.scale.valueChanged.connect(self.schedule)
        f2.addRow("Largeur", self.scale)
        self.ipos = QComboBox()
        self.ipos.addItem("Centre", "centre")
        self.ipos.addItem("Haut", "haut")
        self.ipos.addItem("Bas", "bas")
        self.ipos.currentIndexChanged.connect(self.schedule)
        f2.addRow("Position", self.ipos)
        self.tabs.addTab(w, "Image")
        self.tabs.currentChanged.connect(self.schedule)
        lay.addWidget(self.tabs)

        form = QFormLayout()
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(25)
        self.opacity.valueChanged.connect(self.schedule)
        form.addRow("Opacité", self.opacity)
        self.mosaic = QCheckBox("Répéter en mosaïque")
        self.mosaic.toggled.connect(self.schedule)
        form.addRow("", self.mosaic)
        self.under = QCheckBox("Placer sous le contenu")
        self.under.toggled.connect(self.schedule)
        form.addRow("", self.under)
        self.pages = QLineEdit()
        self.pages.setPlaceholderText("toutes")
        form.addRow("Pages", self.pages)
        lay.addLayout(form)
        lay.addWidget(_label("« Sous le contenu » : le filigrane ne masque pas le texte, mais peut être caché par "
                             "les images ou fonds de page.", "hint"))

    def _choose_img(self):
        from PySide6.QtWidgets import QFileDialog
        p, _ = QFileDialog.getOpenFileName(self, "Image du filigrane", last_dir(), IMG_FILTER)
        if p:
            remember_dir(p)
            self.img_path = p
            self.img_btn.setText(Path(p).name)
            self.schedule()

    def _call(self, src, pw, out, pages=None):
        common = dict(opacity=self.opacity.value() / 100, mosaic=self.mosaic.isChecked(),
                      under=self.under.isChecked(), pages=pages)
        if self.tabs.currentIndex() == 0:
            return core.add_text_watermark, (src, pw, out), dict(
                text=self.text.text(), font_size=self.tsize.value(), color=self.tcolor.color(),
                angle=self.angle.currentData(), bold=self.tbold.isChecked(), **common)
        if not self.img_path:
            raise core.PdfError("Choisissez l'image du filigrane.")
        return core.add_image_watermark, (src, pw, out), dict(
            image=self.img_path, scale=self.scale.value() / 100, position=self.ipos.currentData(), **common)

    def preview_call(self, src, out):
        fn, a, kw = self._call(src, None, out)
        fn(*a, **kw)

    def task(self):
        pages = self.pages.text().strip() or None
        if pages:
            core.parse_pages(pages, self.page_count)
        fn, a, kw = self._call(self.src, self.pw, None, pages)
        out = ask_save_pdf(self, suggest_output(self.src, "filigrane"))
        if not out:
            return None
        return fn, (self.src, self.pw, out), kw, lambda res: self.done_dialog(
            "Votre PDF est prêt", "Le filigrane a été ajouté.", [res])


# --------------------------------------------------------------------------
# Rogner
# --------------------------------------------------------------------------
class CropCanvas(QWidget):
    rect_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 420)
        self.img: QImage | None = None
        self.ratio = QRectF(0.05, 0.05, 0.9, 0.9)  # x, y, w, h en proportions
        self._drag = None
        self.setMouseTracking(True)

    def set_image(self, img: QImage):
        self.img = img
        self.update()

    def _page_rect(self) -> QRectF:
        if self.img is None:
            return QRectF()
        s = min((self.width() - 30) / self.img.width(), (self.height() - 30) / self.img.height())
        w, h = self.img.width() * s, self.img.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _sel(self) -> QRectF:
        pr = self._page_rect()
        r = self.ratio
        return QRectF(pr.x() + r.x() * pr.width(), pr.y() + r.y() * pr.height(), r.width() * pr.width(),
                      r.height() * pr.height())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#e9ecf2"))
        if self.img is None:
            return
        pr = self._page_rect()
        p.drawImage(pr, self.img)
        sel = self._sel()
        shade = QColor(20, 24, 33, 120)
        for r in (QRectF(pr.left(), pr.top(), pr.width(), sel.top() - pr.top()),
                  QRectF(pr.left(), sel.bottom(), pr.width(), pr.bottom() - sel.bottom()),
                  QRectF(pr.left(), sel.top(), sel.left() - pr.left(), sel.height()),
                  QRectF(sel.right(), sel.top(), pr.right() - sel.right(), sel.height())):
            p.fillRect(r, shade)
        p.setPen(QPen(QColor(ACCENT), 2))
        p.drawRect(sel)
        p.setBrush(QColor("white"))
        for pt in (sel.topLeft(), sel.topRight(), sel.bottomLeft(), sel.bottomRight()):
            p.drawEllipse(pt, 5, 5)

    def _hit(self, pos):
        sel = self._sel()
        for i, pt in enumerate((sel.topLeft(), sel.topRight(), sel.bottomRight(), sel.bottomLeft())):
            if (pos - pt).manhattanLength() < 12:
                return ("corner", i)
        if sel.contains(pos):
            return ("move", None)
        return ("new", None)

    def mousePressEvent(self, e):
        pos = e.position()
        kind, idx = self._hit(pos)
        self._drag = (kind, idx, pos, QRectF(self._sel()))

    def mouseMoveEvent(self, e):
        pos = e.position()
        if not self._drag:
            kind, idx = self._hit(pos)
            self.setCursor(Qt.SizeAllCursor if kind == "move" else Qt.CrossCursor)
            return
        kind, idx, start, sel0 = self._drag
        pr = self._page_rect()
        if kind == "move":
            r = sel0.translated(pos - start)
            r.moveLeft(min(max(r.left(), pr.left()), pr.right() - r.width()))
            r.moveTop(min(max(r.top(), pr.top()), pr.bottom() - r.height()))
        elif kind == "corner":
            corners = [sel0.topLeft(), sel0.topRight(), sel0.bottomRight(), sel0.bottomLeft()]
            r = QRectF(corners[(idx + 2) % 4], pos).normalized()
        else:
            r = QRectF(start, pos).normalized()
        r = r.intersected(pr)
        if r.width() > 8 and r.height() > 8:
            self.ratio = QRectF((r.x() - pr.x()) / pr.width(), (r.y() - pr.y()) / pr.height(),
                                r.width() / pr.width(), r.height() / pr.height())
            self.update()
            self.rect_changed.emit()

    def mouseReleaseEvent(self, e):
        self._drag = None


class CropTool(ToolPage):
    KEY, TITLE, CAT, ICON = "crop", "Rogner un PDF", "modifier", "crop"
    DESC = "Recadrez les pages : à la souris, par marges précises ou automatiquement."
    ACTION = "Rogner"

    def build_content(self, lay):
        self.canvas = CropCanvas()
        self.canvas.rect_changed.connect(self._canvas_changed)
        lay.addWidget(self.canvas, 1)
        nav = QHBoxLayout()
        nav.addStretch(1)
        self.prev_btn = _btn("", "left", slot=lambda: self._show(self.cur - 1))
        self.next_btn = _btn("", "right", slot=lambda: self._show(self.cur + 1))
        self.page_lab = _label("", "muted", wrap=False)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.page_lab)
        nav.addWidget(self.next_btn)
        nav.addStretch(1)
        lay.addLayout(nav)
        self.cur = 0

    def build_options(self, lay):
        lay.addWidget(_label("Méthode", "section"))
        self.mode = _options(lay, [("mouse", "Sélection à la souris"), ("margins", "Marges précises (mm)"),
                                   ("auto", "Automatique : retirer les marges blanches")])
        lay.addWidget(_label("Marges (mm)", "section"))
        grid = QGridLayout()
        self.m = {}
        for i, (k, lab) in enumerate([("top", "Haut"), ("bottom", "Bas"), ("left", "Gauche"), ("right", "Droite")]):
            sp = QDoubleSpinBox()
            sp.setRange(0, 500)
            sp.setDecimals(1)
            sp.setSuffix(" mm")
            sp.valueChanged.connect(self._margins_changed)
            grid.addWidget(QLabel(lab), i // 2 * 2, i % 2)
            grid.addWidget(sp, i // 2 * 2 + 1, i % 2)
            self.m[k] = sp
        lay.addLayout(grid)
        lay.addWidget(_label("Marge conservée en mode automatique", "section"))
        self.pad = QDoubleSpinBox()
        self.pad.setRange(0, 50)
        self.pad.setValue(5)
        self.pad.setSuffix(" mm")
        lay.addWidget(self.pad)
        lay.addWidget(_label("Pages à rogner", "section"))
        self.scope = _options(lay, [("all", "Toutes les pages"), ("current", "Uniquement la page affichée"),
                                    ("custom", "Pages choisies :")])
        self.pages = QLineEdit()
        self.pages.setPlaceholderText("ex. : 1-3, 5")
        lay.addWidget(self.pages)
        self.mode.idToggled.connect(lambda *_: self._upd())
        self._upd()

    def _upd(self):
        m = _group_value(self.mode)
        for sp in self.m.values():
            sp.setEnabled(m == "margins")
        self.pad.setEnabled(m == "auto")

    def on_files(self, entries):
        doc = core.open_pdf(*entries[0])
        self.n = doc.page_count
        self.sizes = [(p.rect.width, p.rect.height) for p in doc]
        doc.close()
        self._show(0)

    def _show(self, i):
        if not self.entries:
            return
        self.cur = max(0, min(self.n - 1, i))
        img = render_thumbnail(self.src, self.pw, self.cur, 900)
        if img is not None:
            self.canvas.set_image(img)
        self.page_lab.setText(f"  Page {self.cur + 1} / {self.n}  ")
        self.prev_btn.setEnabled(self.cur > 0)
        self.next_btn.setEnabled(self.cur < self.n - 1)
        self._canvas_changed()

    def _canvas_changed(self):
        if not self.entries:
            return
        w, h = self.sizes[self.cur]
        r = self.canvas.ratio
        vals = {"left": r.x() * w / core.MM, "top": r.y() * h / core.MM,
                "right": (1 - r.x() - r.width()) * w / core.MM, "bottom": (1 - r.y() - r.height()) * h / core.MM}
        for k, sp in self.m.items():
            sp.blockSignals(True)
            sp.setValue(max(0.0, vals[k]))
            sp.blockSignals(False)

    def _margins_changed(self):
        if not self.entries:
            return
        w, h = self.sizes[self.cur]
        l, t = self.m["left"].value() * core.MM / w, self.m["top"].value() * core.MM / h
        r, b = self.m["right"].value() * core.MM / w, self.m["bottom"].value() * core.MM / h
        if l + r < 0.95 and t + b < 0.95:
            self.canvas.ratio = QRectF(l, t, 1 - l - r, 1 - t - b)
            self.canvas.update()
        if _group_value(self.mode) == "mouse":
            self.mode.button(1).setChecked(True)

    def task(self):
        scope = _group_value(self.scope)
        pages = None if scope == "all" else (str(self.cur + 1) if scope == "current" else self.pages.text().strip())
        if scope == "custom":
            if not pages:
                raise core.PdfError("Indiquez les pages à rogner.")
            core.parse_pages(pages, self.n)
        out = ask_save_pdf(self, suggest_output(self.src, "rogné"))
        if not out:
            return None
        m = _group_value(self.mode)
        ok = lambda res: self.done_dialog("Votre PDF est prêt", "Les pages ont été rognées.", [res])  # noqa: E731
        if m == "auto":
            return core.auto_crop, (self.src, self.pw, out), {"padding_mm": self.pad.value(), "pages": pages}, ok
        if m == "margins":
            return core.crop_margins, (self.src, self.pw, out), {
                "left": self.m["left"].value(), "top": self.m["top"].value(), "right": self.m["right"].value(),
                "bottom": self.m["bottom"].value(), "pages": pages}, ok
        r = self.canvas.ratio
        return core.crop_rect, (self.src, self.pw, out, (r.left(), r.top(), r.right(), r.bottom())), \
            {"pages": pages}, ok


# --------------------------------------------------------------------------
# Optimiser / sécurité / formulaires
# --------------------------------------------------------------------------
class RepairTool(ToolPage):
    KEY, TITLE, CAT, ICON = "repair", "Réparer un PDF", "optimiser", "repair"
    DESC = "Récupérez un PDF endommagé ou qui s'ouvre mal en reconstruisant sa structure."
    ACTION = "Réparer"

    def build_options(self, lay):
        lay.addWidget(_label("Comment ça marche ?", "section"))
        lay.addWidget(_label("Le fichier est relu page par page puis réécrit proprement dans un nouveau PDF. "
                             "Les pages illisibles sont ignorées.", "hint"))

    def _prepare_entries(self, paths):
        # un PDF abîmé peut échouer à l'ouverture : on l'accepte quand même
        out = []
        for p in paths:
            pw = None
            if core.needs_password(p):
                pw = ask_password(self, p)
                if pw is None:
                    continue
            out.append((str(p), pw))
        return out

    def task(self):
        out = ask_save_pdf(self, suggest_output(self.src, "réparé"))
        if not out:
            return None
        return core.repair, (self.src, self.pw, out), {}, lambda res: self.done_dialog(
            "Réparation terminée", "Des erreurs ont été corrigées dans la structure du fichier." if res else
            "Le fichier ne présentait pas d'erreur détectable ; il a été réécrit proprement.", [out])


class ProtectTool(ToolPage):
    KEY, TITLE, CAT, ICON = "protect", "Protéger un PDF", "securite", "protect"
    DESC = "Chiffrez votre PDF (AES 256 bits) avec un mot de passe et limitez ce que l'on peut en faire."
    ACTION = "Protéger"

    def build_options(self, lay):
        lay.addWidget(_label("Mot de passe d'ouverture", "section"))
        self.pw1 = QLineEdit()
        self.pw1.setEchoMode(QLineEdit.Password)
        self.pw1.setPlaceholderText("Mot de passe")
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        self.pw2.setPlaceholderText("Confirmez le mot de passe")
        lay.addWidget(self.pw1)
        lay.addWidget(self.pw2)
        show = QCheckBox("Afficher le mot de passe")
        show.toggled.connect(lambda on: [w.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
                                         for w in (self.pw1, self.pw2)])
        lay.addWidget(show)
        lay.addWidget(_label("Autorisations", "section"))
        self.p_print = QCheckBox("Autoriser l'impression")
        self.p_print.setChecked(True)
        self.p_copy = QCheckBox("Autoriser la copie du texte")
        self.p_copy.setChecked(True)
        self.p_annot = QCheckBox("Autoriser les annotations et formulaires")
        self.p_annot.setChecked(True)
        self.p_mod = QCheckBox("Autoriser la modification")
        for w in (self.p_print, self.p_copy, self.p_annot, self.p_mod):
            lay.addWidget(w)
        lay.addWidget(_label("Conservez précieusement le mot de passe : il ne pourra pas être retrouvé.", "hint"))

    def task(self):
        if not self.pw1.text():
            raise core.PdfError("Saisissez un mot de passe.")
        if self.pw1.text() != self.pw2.text():
            raise core.PdfError("Les deux mots de passe ne correspondent pas.")
        out = ask_save_pdf(self, suggest_output(self.src, "protégé"))
        if not out:
            return None
        return core.protect, (self.src, self.pw, out), dict(
            user_pw=self.pw1.text(), allow_print=self.p_print.isChecked(), allow_copy=self.p_copy.isChecked(),
            allow_modify=self.p_mod.isChecked(), allow_annotate=self.p_annot.isChecked()), \
            lambda res: self.done_dialog("Votre PDF est protégé", "Il faudra le mot de passe pour l'ouvrir.", [res])


class UnlockTool(ToolPage):
    KEY, TITLE, CAT, ICON = "unlock", "Déverrouiller un PDF", "securite", "unlock"
    DESC = "Retirez le mot de passe et les restrictions d'un PDF dont vous connaissez le mot de passe."
    ACTION = "Déverrouiller"

    def build_options(self, lay):
        lay.addWidget(_label("État du fichier", "section"))
        self.state = _label("", "muted")
        lay.addWidget(self.state)

    def on_files(self, entries):
        super().on_files(entries)
        path, pw = entries[0]
        doc = core.open_pdf(path, pw)
        enc = doc.is_encrypted or bool(pw)
        doc.close()
        if pw:
            self.state.setText("Mot de passe vérifié. Le PDF enregistré s'ouvrira sans mot de passe.")
        elif enc:
            self.state.setText("Ce PDF s'ouvre sans mot de passe mais comporte des restrictions (impression, copie…). "
                               "Elles seront retirées.")
        else:
            self.state.setText("Ce PDF n'est pas protégé : il n'y a rien à déverrouiller.")

    def task(self):
        out = ask_save_pdf(self, suggest_output(self.src, "déverrouillé"))
        if not out:
            return None
        return core.unlock, (self.src, self.pw, out), {}, lambda res: self.done_dialog(
            "PDF déverrouillé", "Le fichier enregistré n'a plus de mot de passe ni de restriction.", [res])


class FormTool(ToolPage):
    KEY, TITLE, CAT, ICON = "form", "Remplir un formulaire", "modifier", "form"
    DESC = "Complétez les champs d'un formulaire PDF, puis figez-le si besoin."
    ACTION = "Enregistrer le formulaire"

    def build_content(self, lay):
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.form_box = QFrame()
        self.form_box.setObjectName("box")
        self.scroll.setWidget(self.form_box)
        lay.addWidget(self.scroll, 1)
        self.widgets = {}

    def build_options(self, lay):
        lay.addWidget(_label("Options", "section"))
        self.flatten = QCheckBox("Figer le formulaire (les champs ne seront plus modifiables)")
        lay.addWidget(self.flatten)
        self.info = _label("", "muted")
        lay.addWidget(self.info)

    def on_files(self, entries):
        fields = core.get_form_fields(*entries[0])
        self.widgets = {}
        box = QFrame()
        box.setObjectName("box")
        form = QFormLayout(box)
        form.setContentsMargins(24, 20, 24, 20)
        form.setVerticalSpacing(10)
        if not fields:
            lab = _label("Ce PDF ne contient aucun champ de formulaire.\n\nPour écrire dessus, utilisez l'outil "
                         "« Modifier le PDF » (Texte).", "muted")
            form.addRow(lab)
            b = _btn("Ouvrir dans l'éditeur", "edit", slot=lambda: self.main.open_editor(*self.entries[0], "edit"))
            form.addRow(b)
            self.run_btn.setEnabled(False)
        else:
            self.run_btn.setEnabled(True)
            page = None
            for f in fields:
                if f["page"] != page:
                    page = f["page"]
                    form.addRow(_label(f"Page {page}", "section"))
                kind = f["type"]
                if kind == "texte":
                    w = QLineEdit(f["value"] or "")
                elif kind == "case":
                    w = QCheckBox()
                    w.setChecked(bool(f["value"]))
                else:
                    w = QComboBox()
                    w.addItem("", None)
                    for o in f["options"]:
                        w.addItem(str(o), o)
                    if f["value"] is not None:
                        w.setCurrentIndex(max(0, w.findData(f["value"])))
                w.setEnabled(not f["readonly"])
                self.widgets[f["name"]] = (kind, w)
                form.addRow(f["label"][:60], w)
        self.scroll.setWidget(box)
        self.info.setText(f"{len(fields)} champ(s) trouvé(s).")

    def task(self):
        values = {}
        for name, (kind, w) in self.widgets.items():
            if kind == "texte":
                values[name] = w.text()
            elif kind == "case":
                values[name] = w.isChecked()
            else:
                values[name] = w.currentData()
                if values[name] is None:
                    del values[name]
        out = ask_save_pdf(self, suggest_output(self.src, "rempli"))
        if not out:
            return None
        return core.fill_form, (self.src, self.pw, out, values), {"flatten": self.flatten.isChecked()}, \
            lambda res: self.done_dialog("Formulaire enregistré", "Vos réponses ont été enregistrées.", [res])


# --------------------------------------------------------------------------
# Éditeur, signature, caviardage
# --------------------------------------------------------------------------
class EditorLauncher(ToolPage):
    MODE = "edit"

    def build_options(self, lay):
        lay.addWidget(_label("Éditeur", "section"))
        lay.addWidget(_label(self.HELP, "hint"))

    def on_files(self, entries):
        super().on_files(entries)
        QTimer.singleShot(100, self.run)

    def run(self):
        if self.entries:
            self.main.open_editor(self.src, self.pw, self.MODE)


class EditTool(EditorLauncher):
    KEY, TITLE, CAT, ICON = "edit", "Modifier le PDF", "modifier", "edit"
    DESC = "Ajoutez du texte, des images, des formes, des surlignages, des commentaires ou masquez une zone."
    ACTION = "Ouvrir l'éditeur"
    MODE = "edit"
    HELP = ("L'éditeur s'ouvre dans une nouvelle fenêtre. Choisissez un outil dans la barre du haut puis cliquez "
            "dans la page. Le fichier d'origine n'est jamais modifié : vous enregistrez une nouvelle version.")


class SignTool(EditorLauncher):
    KEY, TITLE, CAT, ICON = "sign", "Signer un PDF", "securite", "sign"
    DESC = "Dessinez, saisissez ou importez votre signature et placez-la sur le document."
    ACTION = "Ouvrir pour signer"
    MODE = "sign"
    HELP = ("Créez votre signature (elle peut être mémorisée pour la prochaine fois), puis placez-la sur la page. "
            "Il s'agit d'une signature visuelle (image), et non d'une signature électronique certifiée.")


class RedactTool(EditorLauncher):
    KEY, TITLE, CAT, ICON = "redact", "Caviarder un PDF", "securite", "redact"
    DESC = "Supprimez définitivement des informations sensibles (noms, adresses, montants…)."
    ACTION = "Ouvrir pour caviarder"
    MODE = "redact"
    HELP = ("Tracez des zones noires ou recherchez un mot dans tout le document. À l'enregistrement, le texte, "
            "les images et les tracés situés dessous sont réellement supprimés du fichier.")


# --------------------------------------------------------------------------
# Comparer
# --------------------------------------------------------------------------
class FileSlot(QFrame):
    changed = Signal()

    def __init__(self, title, page):
        super().__init__()
        self.setObjectName("box")
        self.page = page
        self.entry = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.addWidget(_label(title, "h2"))
        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setMinimumHeight(300)
        lay.addWidget(self.thumb, 1)
        self.name = _label("Aucun fichier", "muted")
        self.name.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.name)
        b = _btn(" Choisir un PDF", "upload", slot=self.browse)
        lay.addWidget(b, 0, Qt.AlignCenter)
        accept_file_drops(self, lambda paths: self.set_paths(paths[:1]), "pdf")

    def browse(self):
        from PySide6.QtWidgets import QFileDialog
        p, _ = QFileDialog.getOpenFileName(self, "Choisir un PDF", last_dir(), PDF_FILTER)
        if p:
            remember_dir(p)
            self.set_paths([p])

    def set_paths(self, paths):
        entries = self.page._prepare_entries(paths)
        if not entries:
            return
        self.entry = entries[0]
        img = render_thumbnail(*self.entry, 0, 360)
        if img is not None:
            self.thumb.setPixmap(QPixmap.fromImage(img).scaled(260, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.name.setText(Path(self.entry[0]).name)
        self.changed.emit()


class CompareTool(ToolPage):
    KEY, TITLE, CAT, ICON = "compare", "Comparer deux PDF", "securite", "compare"
    DESC = "Repérez les différences de texte entre deux versions d'un document (contrat, convention…)."
    ACTION = "Comparer"

    def __init__(self, main):
        super().__init__(main)
        self.stack.setCurrentIndex(1)
        self._upd()

    def build_content(self, lay):
        row = QHBoxLayout()
        self.a = FileSlot("Version d'origine", self)
        self.b = FileSlot("Nouvelle version", self)
        row.addWidget(self.a)
        row.addWidget(self.b)
        lay.addLayout(row, 1)
        self.a.changed.connect(self._upd)
        self.b.changed.connect(self._upd)

    def build_options(self, lay):
        lay.addWidget(_label("Résultat", "section"))
        lay.addWidget(_label("Un rapport PDF est créé : d'abord la liste des différences, puis les pages côte à côte "
                             "avec les suppressions surlignées en rouge et les ajouts en vert.", "hint"))
        lay.addWidget(_label("La comparaison porte sur le texte. Pour un document scanné (image), elle ne "
                             "détectera rien.", "hint"))

    def load_files(self, paths):
        if not self.a.entry:
            self.a.set_paths(paths[:1])
            paths = paths[1:]
        if paths:
            self.b.set_paths(paths[:1])

    def _upd(self):
        self.run_btn.setEnabled(bool(self.a.entry and self.b.entry))
        self.reset_btn.setVisible(bool(self.a.entry or self.b.entry))

    def reset(self):
        for s in (self.a, self.b):
            s.entry = None
            s.thumb.clear()
            s.name.setText("Aucun fichier")
        self._upd()

    def task(self):
        if not (self.a.entry and self.b.entry):
            raise core.PdfError("Choisissez les deux versions à comparer.")
        (pa, wa), (pb, wb) = self.a.entry, self.b.entry
        out = ask_save_pdf(self, suggest_output(pb, "comparaison"))
        if not out:
            return None

        def ok(res):
            if res["identical"]:
                self.done_dialog("Aucune différence", "Le texte des deux documents est identique.", [out])
                return
            lines = []
            for i, c in enumerate(res["changes"][:200], 1):
                where = f"p. {c['page_a'] or '–'} → p. {c['page_b'] or '–'}"
                txt = f"{i}. {c['type']} ({where})"
                if c["old"]:
                    txt += f"\n   − {c['old'][:200]}"
                if c["new"]:
                    txt += f"\n   + {c['new'][:200]}"
                lines.append(txt)
            self.done_dialog(f"{len(res['changes'])} différence(s) trouvée(s)",
                             "Le rapport détaillé a été enregistré. Aperçu :", [out], details="\n".join(lines))
        return core.compare, (pa, wa, pb, wb, out), {}, ok


ALL_TOOLS = [MergeTool, SplitTool, DeleteTool, ExtractTool, OrganizeTool,
             CompressTool, RepairTool,
             ImagesToPdfTool, PdfToImagesTool,
             EditTool, RotateTool, NumbersTool, WatermarkTool, CropTool, FormTool,
             ProtectTool, UnlockTool, SignTool, RedactTool, CompareTool]
