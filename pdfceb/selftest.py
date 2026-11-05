"""Autotest de PDF Ceb : exerce chaque opération sur des fichiers générés.

Utilisé par les tests automatisés et par « PDF-Ceb.exe --selftest » lors de la
compilation, pour vérifier que l'exécutable Windows embarque bien tout le
nécessaire.
"""
from __future__ import annotations

import io
import tempfile
import traceback
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from . import core

LOREM = ("Le présent contrat est conclu entre la société Alpha et la société Bêta. "
         "Il prend effet à compter de sa signature pour une durée de trois ans. "
         "Le prix est fixé à dix mille euros hors taxes, payable à trente jours.")


def make_samples(d: Path) -> dict:
    d.mkdir(parents=True, exist_ok=True)
    # Image photo (paysage) et PNG transparent
    photo = Image.new("RGB", (800, 500), (30, 90, 160))
    dr = ImageDraw.Draw(photo)
    for i in range(0, 800, 40):
        dr.rectangle([i, 0, i + 20, 500], fill=(200, 120 + i % 100, 60))
    photo_path = d / "photo.jpg"
    photo.save(photo_path, "JPEG", quality=90)
    logo = Image.new("RGBA", (300, 150), (0, 0, 0, 0))
    ImageDraw.Draw(logo).ellipse([10, 10, 290, 140], fill=(220, 30, 30, 255))
    logo_path = d / "logo.png"
    logo.save(logo_path)

    # Document A : 5 pages, la page 3 est tournée de 90°
    a = pymupdf.open()
    for n in range(1, 6):
        p = a.new_page()
        p.insert_text((72, 80), f"Page {n}", fontsize=20)
        p.insert_textbox(pymupdf.Rect(72, 110, 520, 300), LOREM + f" Clause numéro {n}.", fontsize=11)
        if n == 2:
            p.insert_image(pymupdf.Rect(72, 320, 372, 507), filename=str(photo_path))
        if n == 3:
            p.set_rotation(90)
    a.set_toc([[1, "Début", 1], [1, "Milieu", 3]])
    a_path = d / "contrat_v1.pdf"
    a.save(a_path)

    # Document B : version modifiée de A
    b = pymupdf.open()
    for n in range(1, 6):
        p = b.new_page()
        p.insert_text((72, 80), f"Page {n}", fontsize=20)
        txt = LOREM.replace("trois ans", "cinq ans") if n == 2 else LOREM
        if n == 4:
            txt = txt.replace("dix mille", "douze mille")
        p.insert_textbox(pymupdf.Rect(72, 110, 520, 300), txt + f" Clause numéro {n}.", fontsize=11)
    b_path = d / "contrat_v2.pdf"
    b.save(b_path)

    # Formulaire
    f = pymupdf.open()
    p = f.new_page()
    w = pymupdf.Widget()
    w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    w.field_name = "nom"
    w.rect = pymupdf.Rect(72, 72, 300, 92)
    p.add_widget(w)
    w = pymupdf.Widget()
    w.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
    w.field_name = "accord"
    w.rect = pymupdf.Rect(72, 110, 86, 124)
    p.add_widget(w)
    w = pymupdf.Widget()
    w.field_type = pymupdf.PDF_WIDGET_TYPE_COMBOBOX
    w.field_name = "ville"
    w.choice_values = ["Orléans", "Tours", "Blois"]
    w.field_value = "Orléans"
    w.rect = pymupdf.Rect(72, 140, 300, 160)
    p.add_widget(w)
    form_path = d / "formulaire.pdf"
    f.save(form_path)
    return dict(a=a_path, b=b_path, form=form_path, photo=photo_path, logo=logo_path)


def _text(path, pno=0, pw=None):
    doc = core.open_pdf(path, pw)
    t = doc[pno].get_text()
    doc.close()
    return t


def _count(path, pw=None):
    doc = core.open_pdf(path, pw)
    n = doc.page_count
    doc.close()
    return n


def run(workdir: Path | None = None) -> list[tuple[str, bool, str]]:
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="pdfceb_test_"))
    s = make_samples(tmp / "in")
    o = tmp / "out"
    o.mkdir(parents=True, exist_ok=True)
    results = []

    def check(name, fn):
        try:
            fn()
            results.append((name, True, ""))
        except Exception as exc:  # noqa: BLE001
            results.append((name, False, f"{exc}\n{traceback.format_exc()}"))

    def t_parse():
        assert core.parse_pages("1-3, 5, 8-", 10) == [0, 1, 2, 4, 7, 8, 9]
        assert core.parse_pages("-2", 5) == [0, 1]
        assert core.parse_pages("fin", 4) == [3]
        assert core.parse_pages("pair", 5) == [1, 3]
        assert core.parse_pages("3,1", 5) == [2, 0]
        assert core.parse_groups("1-2; 3, 4-5", 5) == [[0, 1], [2], [3, 4]]
        try:
            core.parse_pages("7", 5)
            raise AssertionError("page hors limites acceptée")
        except core.PdfError:
            pass

    def t_merge():
        out = core.merge([(s["a"], None), (s["b"], None), (s["photo"], None)], o / "fusion.pdf")
        assert _count(out) == 11
        doc = pymupdf.open(out)
        titles = [t[1] for t in doc.get_toc()]
        assert "contrat_v1" in titles and "Milieu" in titles, titles

    def t_split():
        outs = core.split_groups(s["a"], None, core.parse_groups("1-2, 3, 4-5", 5), o / "div")
        assert [_count(x) for x in outs] == [2, 1, 2]
        outs = core.split_every(s["a"], None, 2, o / "div2")
        assert [_count(x) for x in outs] == [2, 2, 1]

    def t_delete_extract():
        out = core.delete_pages(s["a"], None, [0, 2], o / "suppr.pdf")
        assert _count(out) == 3 and "Page 2" in _text(out, 0)
        out = core.extract_pages(s["a"], None, [4, 0], o / "extrait.pdf")
        assert _count(out) == 2 and "Page 5" in _text(out, 0) and "Page 1" in _text(out, 1)

    def t_organize():
        items = [{"src": 1, "page": 0}, {"blank": True}, {"src": 0, "page": 3, "rot": 90}, {"src": 0, "page": 2, "rot": 270}]
        out = core.organize([(s["a"], None), (s["b"], None)], items, o / "organise.pdf")
        doc = pymupdf.open(out)
        assert doc.page_count == 4
        assert doc[2].rotation == 90 and doc[3].rotation == 0
        assert doc[1].get_text().strip() == ""

    def t_rotate():
        out = core.rotate_pages(s["a"], None, {0: 90, 1: 180}, o / "pivot.pdf")
        doc = pymupdf.open(out)
        assert doc[0].rotation == 90 and doc[1].rotation == 180 and doc[2].rotation == 90

    def t_numbers():
        out = core.add_page_numbers(s["a"], None, o / "numeros.pdf", fmt="Page {n} sur {total}",
                                    position="bas-droite")
        doc = pymupdf.open(out)
        assert "Page 1 sur 5" in doc[0].get_text()
        assert "Page 3 sur 5" in doc[2].get_text()
        # sur la page tournée, le numéro doit être horizontal et en bas à droite
        words = [w for w in doc[2].get_text("words") if w[4] == "sur"]
        x0, y0, x1, y1 = words[0][:4]
        assert (x1 - x0) > (y1 - y0), "numéro de page non horizontal"
        assert y1 > doc[2].rect.height * 0.9 and x1 > doc[2].rect.width * 0.8

    def t_watermark():
        out = core.add_text_watermark(s["a"], None, o / "filigrane.pdf", text="CONFIDENTIEL — Copie",
                                      opacity=0.2)
        assert "CONFIDENTIEL" in _text(out, 2)
        out = core.add_text_watermark(s["a"], None, o / "filigrane2.pdf", text="BROUILLON", mosaic=True,
                                      under=True, pages="1")
        assert _text(out, 0).count("BROUILLON") >= 4 and "BROUILLON" not in _text(out, 1)
        out = core.add_image_watermark(s["a"], None, o / "filigrane_img.pdf", image=s["logo"], opacity=0.3)
        doc = pymupdf.open(out)
        assert len(doc[0].get_images()) == 1

    def t_crop():
        out = core.crop_margins(s["a"], None, o / "rogne.pdf", left=20, right=20, top=10, bottom=10)
        doc = pymupdf.open(out)
        r0 = doc[0].rect
        assert abs(r0.width - (595 - 40 * core.MM)) < 1.5, r0
        r2 = doc[2].rect  # page tournée : largeur affichée = 842
        assert abs(r2.width - (842 - 40 * core.MM)) < 1.5 and abs(r2.height - (595 - 20 * core.MM)) < 1.5, r2
        out = core.auto_crop(s["a"], None, o / "rogne_auto.pdf")
        doc = pymupdf.open(out)
        assert doc[0].rect.width < 560 and doc[0].rect.height < 400, doc[0].rect
        assert "Page 1" in doc[0].get_text()

    def t_compress_repair():
        big = pymupdf.open()
        img = Image.effect_noise((2400, 1800), 60).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        pg = big.new_page()
        pg.insert_image(pg.rect, stream=buf.getvalue())
        big.save(o / "lourd.pdf")
        before, after = core.compress(o / "lourd.pdf", None, o / "leger.pdf", "forte")
        assert after < before * 0.6, (before, after)
        assert _count(o / "leger.pdf") == 1
        data = bytearray(Path(s["a"]).read_bytes())
        k = data.rfind(b"startxref")
        broken = bytes(data[:k]) + b"startxref\n999999\n%%EOF"
        (o / "abime.pdf").write_bytes(broken)
        core.repair(o / "abime.pdf", None, o / "repare.pdf")
        assert _count(o / "repare.pdf") == 5

    def t_security():
        out = core.protect(s["a"], None, o / "protege.pdf", user_pw="Secret#1", allow_copy=False)
        assert core.needs_password(out)
        assert core.check_password(out, "Secret#1") and not core.check_password(out, "faux")
        try:
            core.open_pdf(out)
            raise AssertionError("PDF protégé ouvert sans mot de passe")
        except core.PasswordRequired:
            pass
        out2 = core.unlock(out, "Secret#1", o / "deverrouille.pdf")
        assert not core.needs_password(out2) and _count(out2) == 5

    def t_images():
        out = core.images_to_pdf([s["photo"], s["logo"]], o / "images.pdf", page_size="A4")
        doc = pymupdf.open(out)
        assert doc.page_count == 2 and doc[0].rect.width > doc[0].rect.height
        out = core.images_to_pdf([s["photo"]], o / "image_taille.pdf", page_size="image")
        assert abs(pymupdf.open(out)[0].rect.width - 600) < 1
        outs = core.images_to_pdfs([s["photo"], s["logo"]], o / "images_sep")
        assert len(outs) == 2
        outs = core.pdf_to_images(s["a"], None, o / "jpg", "jpg", 72, pages="1-2")
        assert len(outs) == 2 and Path(outs[0]).stat().st_size > 1000
        outs = core.pdf_to_images(s["a"], None, o / "png", "png", 50)
        assert len(outs) == 5
        outs = core.extract_images(s["a"], None, o / "extraites")
        assert len(outs) == 1

    def t_forms():
        fields = core.get_form_fields(s["form"])
        names = {f["name"]: f for f in fields}
        assert set(names) == {"nom", "accord", "ville"}, names
        assert names["ville"]["options"] == ["Orléans", "Tours", "Blois"]
        out = core.fill_form(s["form"], None, o / "rempli.pdf", {"nom": "Seb Ébène", "accord": True, "ville": "Tours"})
        vals = {f["name"]: f["value"] for f in core.get_form_fields(out)}
        assert vals["nom"] == "Seb Ébène" and vals["accord"] is True and vals["ville"] == "Tours", vals
        out = core.fill_form(s["form"], None, o / "rempli_plat.pdf", {"nom": "Seb"}, flatten=True)
        doc = pymupdf.open(out)
        assert not list(doc[0].widgets()) and "Seb" in doc[0].get_text()

    def t_compare():
        res = core.compare(s["a"], None, s["b"], None, o / "comparaison.pdf")
        assert not res["identical"]
        olds = " ".join(c["old"] for c in res["changes"])
        news = " ".join(c["new"] for c in res["changes"])
        assert "trois" in olds and "cinq" in news and "douze" in news, res["changes"]
        assert _count(o / "comparaison.pdf") >= 6
        res2 = core.compare(s["b"], None, s["b"], None, o / "comparaison_id.pdf")
        assert res2["identical"]

    def t_edit():
        sig = Image.new("RGBA", (200, 80), (0, 0, 0, 0))
        ImageDraw.Draw(sig).line([(10, 60), (60, 10), (110, 60), (190, 20)], fill=(20, 40, 160, 255), width=5)
        buf = io.BytesIO()
        sig.save(buf, "PNG")
        found = core.search_text_rects(s["a"], None, "Bêta")
        assert set(found) == {0, 1, 2, 3, 4}, found
        edits = {
            0: [
                {"type": "redact", "rect": found[0][0]},
                {"type": "whiteout", "rect": (60, 60, 200, 95)},
                {"type": "text", "rect": (72, 62, 300, 90), "text": "Été à Orléans — n° 1", "size": 16,
                 "color": "#1a237e", "bold": True},
                {"type": "rect", "rect": (300, 400, 400, 450), "stroke": "#d32f2f", "width": 2},
                {"type": "ellipse", "rect": (420, 400, 500, 450), "stroke": "#000000", "fill": "#ffeb3b", "opacity": 0.5},
                {"type": "arrow", "p1": (100, 600), "p2": (250, 650), "stroke": "#000000", "width": 2},
                {"type": "line", "p1": (100, 700), "p2": (250, 700)},
                {"type": "ink", "strokes": [[(300, 600), (320, 620), (340, 600)]], "stroke": "#0000ff", "width": 3},
                {"type": "image", "rect": (350, 700, 500, 760), "data": buf.getvalue()},
                {"type": "highlight", "rect": (72, 110, 300, 125)},
                {"type": "note", "point": (520, 100), "text": "À vérifier"},
            ],
            2: [
                {"type": "redact", "rect": found[2][0]},
                {"type": "text", "rect": (50, 500, 400, 530), "text": "Texte ajouté", "size": 14},
            ],
        }
        out = core.apply_edits(s["a"], None, o / "modifie.pdf", edits, scrub_metadata=True)
        doc = pymupdf.open(out)
        t0 = doc[0].get_text()
        assert "Bêta" not in t0 and "Alpha" in t0, t0
        assert "Été à Orléans — n° 1" in t0, t0
        kinds = sorted(a.type[1] for a in doc[0].annots())
        assert kinds == ["Highlight", "Text"], kinds
        assert len(doc[0].get_images()) == 1
        t2 = doc[2].get_text()
        assert "Bêta" not in t2 and "Texte ajouté" in t2, t2
        w = [w for w in doc[2].get_text("words") if w[4] == "ajouté"][0]
        assert (w[2] - w[0]) > (w[3] - w[1]), "texte ajouté non horizontal sur la page tournée"
        assert 480 < w[1] < 540, w

    for name, fn in [
        ("Sélection de pages", t_parse), ("Fusionner", t_merge), ("Diviser", t_split),
        ("Supprimer / extraire", t_delete_extract), ("Organiser", t_organize), ("Pivoter", t_rotate),
        ("Numéros de pages", t_numbers), ("Filigranes", t_watermark), ("Rogner", t_crop),
        ("Compresser / réparer", t_compress_repair), ("Protéger / déverrouiller", t_security),
        ("Images ↔ PDF", t_images), ("Formulaires", t_forms), ("Comparer", t_compare),
        ("Éditeur et caviardage", t_edit),
    ]:
        check(name, fn)
    return results


def main(log_path: str | None = None) -> int:
    results = run()
    lines = [f"{'OK ' if ok else 'ÉCHEC'} {name}" + (f"\n{msg}" if msg else "") for name, ok, msg in results]
    text = "\n".join(lines)
    if log_path:
        Path(log_path).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
