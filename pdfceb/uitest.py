"""Test automatique de l'interface (sans affichage).

Ouvre chaque outil, y charge des fichiers d'exemple, exécute l'opération en
remplaçant les boîtes de dialogue, vérifie le fichier produit et enregistre
une capture d'écran de chaque écran. Utilisé lors de la compilation Windows.
"""
from __future__ import annotations

import tempfile
import time
import traceback
from pathlib import Path


def main(out_dir: str | None = None) -> int:
    out = Path(out_dir or tempfile.mkdtemp(prefix="pdfceb_ui_"))
    out.mkdir(parents=True, exist_ok=True)
    shots = out / "captures"
    shots.mkdir(exist_ok=True)
    log = []
    ok_all = True
    try:
        ok_all = _run(out, shots, log)
    except Exception:  # noqa: BLE001
        log.append("ÉCHEC global\n" + traceback.format_exc())
        ok_all = False
    (out / "uitest.log").write_text("\n".join(log), encoding="utf-8")
    print("\n".join(log))
    return 0 if ok_all else 1


def _run(out: Path, shots: Path, log: list) -> bool:
    import pymupdf
    from PySide6.QtCore import QPointF, QRectF, QThreadPool
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import core, selftest
    from .app import make_app
    from .ui import editor as editor_mod
    from .ui import tools as tools_mod
    from .ui import widgets as widgets_mod

    app = make_app(["pdfceb"])
    samples = selftest.make_samples(out / "exemples")
    res_dir = out / "resultats"
    res_dir.mkdir(exist_ok=True)
    errors: list[str] = []
    results: list = []

    # remplacement des boîtes de dialogue
    counter = {"n": 0}

    def fake_save(parent, suggested):
        counter["n"] += 1
        return str(res_dir / f"{counter['n']:02d}_{Path(suggested).name}")

    def fake_folder(parent, start=None, title=""):
        counter["n"] += 1
        d = res_dir / f"{counter['n']:02d}_dossier"
        d.mkdir(exist_ok=True)
        return str(d)

    tools_mod.ask_save_pdf = fake_save
    tools_mod.ask_folder = fake_folder
    editor_mod.ask_save_pdf = fake_save
    widgets_mod.ResultDialog.exec = lambda self: 0
    tools_mod.ToolPage.done_dialog = lambda self, title, msg, files, folder=None, details=None: results.append(
        (title, msg, list(files)))
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QMessageBox.warning = staticmethod(lambda parent, title, msg, *a, **k: errors.append(f"{title} : {msg}"))

    def pump(seconds=0.4):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    def wait_tasks():
        for _ in range(600):
            QThreadPool.globalInstance().waitForDone(50)
            app.processEvents()
            if QThreadPool.globalInstance().activeThreadCount() == 0:
                break
        pump(0.2)

    from .ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1440, 920)
    win.show()
    pump(0.5)
    win.grab().save(str(shots / "00_accueil.png"))

    a, b, form, photo, logo, broken = (str(samples[k]) for k in ("a", "b", "form", "photo", "logo", "broken"))
    plan = {
        "merge": ([a, broken, b, photo], None),
        "split": ([a], lambda p: p.ranges.setText("1-2, 3-5")),
        "delete": ([a], lambda p: p.grid.select_pages([0, 2])),
        "extract": ([a], lambda p: (p.range_edit.setText("2, 4-5"), p._range_typed())),
        "organize": ([a], lambda p: (p._add_paths([b]), p.grid.select_pages([0]), p.grid.rotate_selected(90),
                                     p._move(1), p._blank())),
        "compress": ([a], None),
        "repair": ([a], None),
        "img2pdf": ([photo, logo], None),
        "pdf2img": ([a], None),
        "rotate": ([a], lambda p: (p.grid.select_pages([1]), p.grid.rotate_selected(90))),
        "numbers": ([a], lambda p: p.fmt.setCurrentText("Page {n} sur {total}")),
        "watermark": ([a], lambda p: p.text.setText("BROUILLON — Été")),
        "crop": ([a], None),
        "form": ([form], lambda p: (p.widgets["nom"][1].setText("Seb"), p.widgets["accord"][1].setChecked(True))),
        "protect": ([a], lambda p: (p.pw1.setText("Secret1"), p.pw2.setText("Secret1"))),
        "unlock": ([a], None),
    }
    ok_all = True
    for i, (key, (files, setup)) in enumerate(plan.items(), start=1):
        errors.clear()
        results.clear()
        try:
            page = win.open_tool(key)
            page.load_files(files)
            pump(0.8)
            if setup:
                setup(page)
                pump(0.4)
            page.grab().save(str(shots / f"{i:02d}_{key}.png"))
            page.run()
            wait_tasks()
            if errors:
                raise AssertionError("; ".join(errors))
            assert results, "aucun résultat produit"
            produced = results[-1][2]
            assert produced and all(Path(f).exists() for f in produced), produced
            log.append(f"OK  {key} → {len(produced)} fichier(s) · {results[-1][1]}")
        except Exception:  # noqa: BLE001
            ok_all = False
            log.append(f"ÉCHEC {key}\n{traceback.format_exc()}")
        win.show_home()

    # Comparer
    try:
        errors.clear()
        results.clear()
        page = win.open_tool("compare")
        page.a.set_paths([a])
        page.b.set_paths([b])
        pump(0.3)
        page.grab().save(str(shots / "17_compare.png"))
        page.run()
        wait_tasks()
        assert results and not errors, errors
        log.append(f"OK  compare · {results[-1][0]}")
    except Exception:  # noqa: BLE001
        ok_all = False
        log.append("ÉCHEC compare\n" + traceback.format_exc())

    # Éditeur
    try:
        errors.clear()
        page = win.open_tool("edit")
        page.load_files([a])
        pump(1.0)
        ed = win.editors[-1]
        ed.showNormal()
        ed.resize(1440, 900)
        pump(1.0)
        ed.fit_width()
        pump(0.6)
        pg = ed.pages[0]
        t = editor_mod.TextItem("Bonjour Été — n° 42", ed._style_for("text"))
        t.setPos(72, 380)
        ed._add(t, pg)
        r = editor_mod.BoxItem("rect", QRectF(300, 420, 120, 60), ed._style_for("rect"))
        ed._add(r, pg)
        arrow = editor_mod.LineItem("arrow", QPointF(80, 520), ed._style_for("arrow"))
        ed._add(arrow, pg)
        arrow.set_end(QPointF(260, 600))
        hl = editor_mod.BoxItem("highlight", QRectF(70, 108, 250, 16), ed._style_for("highlight"))
        ed._add(hl, pg)
        found = core.search_text_rects(a, None, "Bêta")
        ed._add(editor_mod.BoxItem("redact", QRectF(QPointF(*found[0][0][:2]), QPointF(*found[0][0][2:]))), pg)
        from .ui.signature import SignaturePad, qimage_to_png
        pad = SignaturePad()
        pad.resize(560, 220)
        pad.strokes = [[QPointF(40, 150), QPointF(90, 60), QPointF(140, 160), QPointF(220, 70), QPointF(300, 140)]]
        sig = pad.to_image()
        ed._place_box("image", sig, qimage_to_png(sig), 150)
        r.setSelected(True)
        pump(0.8)
        ed.grab().save(str(shots / "18_editeur.png"))
        results.clear()
        out_before = counter["n"]
        ed.save()
        wait_tasks()
        assert not errors, errors
        produced = sorted(res_dir.glob(f"{out_before + 1:02d}_*"))
        assert produced, "pas de fichier enregistré par l'éditeur"
        with pymupdf.open(produced[0]) as d:
            txt = d[0].get_text()
            assert "Bonjour Été — n° 42" in txt, txt
            assert "Bêta" not in txt.split("Bonjour")[0] or "Bêta" not in txt, "caviardage non appliqué"
            assert len(d[0].get_images()) >= 1
        log.append(f"OK  éditeur → {produced[0].name}")
        ed.dirty = False
        ed.close()
    except Exception:  # noqa: BLE001
        ok_all = False
        log.append("ÉCHEC éditeur\n" + traceback.format_exc())

    # Modifier le texte existant
    try:
        errors.clear()
        txt_src = selftest.make_text_sample(out / "exemples" / "convention.pdf")
        if txt_src is None:
            log.append("--  modifier le texte : aucune police de test disponible, étape ignorée")
        else:
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            ed = win.open_editor(str(txt_src), None, "edit")
            ed.showNormal()
            ed.resize(1440, 900)
            pump(0.8)
            ed.fit_width()
            pump(0.5)
            v = ed.view
            pg = ed.pages[0]

            def to_view(x, y):
                return v.mapFromScene(pg.mapToScene(QPointF(x, y)))

            ed.set_tool("modtext")
            paras = ed.text_page(0).text.paragraphs
            foot = paras[2]
            l0 = foot.lines[0]
            QTest.mouseMove(v.viewport(), to_view(l0.left + 20, l0.baseline - 3))
            pump(0.1)
            QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, to_view(l0.right - 1, l0.baseline - 3))
            pump(0.2)
            assert ed.inline is not None and ed.inline.mode == "line", "éditeur de ligne non ouvert"
            QTest.keyClick(v.viewport(), Qt.Key_End)
            QTest.keyClicks(v.viewport(), " (modifie)")
            pump(0.1)
            ed.grab().save(str(shots / "21_modifier_ligne.png"))
            QTest.keyClick(v.viewport(), Qt.Key_Return)
            pump(0.3)
            body = paras[1]
            l1 = body.lines[1]
            QTest.mouseDClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, to_view(l1.left + 40, l1.baseline - 3))
            pump(0.3)
            assert ed.inline is not None and ed.inline.mode == "para", "éditeur de paragraphe non ouvert"
            it = ed.inline
            i = it.document().toPlainText().find("dix")
            c = it.textCursor()
            c.setPosition(i)
            c.setPosition(i + 3, c.MoveMode.KeepAnchor)
            it.setTextCursor(c)
            QTest.keyClicks(v.viewport(), "onze")
            pump(0.1)
            ed.grab().save(str(shots / "22_modifier_paragraphe.png"))
            QTest.keyClick(v.viewport(), Qt.Key_Return, Qt.ControlModifier)
            pump(0.4)
            ed.grab().save(str(shots / "23_texte_modifie.png"))
            before = counter["n"]
            ed.save()
            wait_tasks()
            assert not errors, errors
            produced = sorted(res_dir.glob(f"{before + 1:02d}_*"))
            assert produced, "pas de fichier enregistré"
            with pymupdf.open(produced[0]) as d:
                t = " ".join(d[0].get_text("text", sort=True).split())
            assert "(modifie)" in t and "onze mille euros" in t and "dix mille" not in t, t
            log.append(f"OK  modifier le texte → {produced[0].name}")
            ed.dirty = False
            ed.close()
    except Exception:  # noqa: BLE001
        ok_all = False
        log.append("ÉCHEC modifier le texte\n" + traceback.format_exc())

    # Fenêtre de signature
    try:
        from .ui.signature import SignatureDialog
        dlg = SignatureDialog(win)
        dlg.tabs.setCurrentIndex(0)
        dlg.pad.strokes = [[QPointF(60, 150), QPointF(110, 60), QPointF(160, 160), QPointF(240, 70),
                            QPointF(330, 140), QPointF(420, 90)]]
        dlg.show()
        pump(0.3)
        dlg.grab().save(str(shots / "19_signature.png"))
        dlg.remember.setChecked(False)
        dlg._accept()
        assert dlg.png and len(dlg.png) > 200
        dlg.tabs.setCurrentIndex(1)
        dlg.name_edit.setText("Seb Martin")
        pump(0.2)
        dlg.grab().save(str(shots / "20_signature_saisie.png"))
        log.append("OK  signature")
        dlg.close()
    except Exception:  # noqa: BLE001
        ok_all = False
        log.append("ÉCHEC signature\n" + traceback.format_exc())

    win.close()
    pump(0.3)
    return ok_all
