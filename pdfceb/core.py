"""Moteur PDF de PDF Ceb.

Toutes les opérations sur les fichiers sont regroupées ici, sans aucune
dépendance à l'interface graphique : cela permet de les tester isolément
et de les réutiliser.

Conventions :
- les numéros de pages manipulés en interne commencent à 0 ;
- les fonctions reçoivent un chemin et, le cas échéant, un mot de passe ;
- les fichiers sources sont lus en mémoire, si bien qu'il est possible
  d'écraser le fichier d'origine sans conflit d'accès sous Windows.
"""
from __future__ import annotations

import difflib
import html
import io
import math
import os
import re
import secrets
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, ImageSequence

try:  # évite que MuPDF n'écrive des avertissements dans la console
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
except Exception:  # pragma: no cover
    pass

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
MM = 72 / 25.4  # 1 mm en points PDF

PAGE_SIZES = {
    "A4": (595.28, 841.89),
    "A3": (841.89, 1190.55),
    "A5": (419.53, 595.28),
    "Lettre US": (612.0, 792.0),
}


# --------------------------------------------------------------------------
# Erreurs
# --------------------------------------------------------------------------
class PdfError(Exception):
    """Erreur présentable telle quelle à l'utilisateur."""


class PasswordRequired(PdfError):
    def __init__(self, path):
        self.path = str(path)
        super().__init__(f"« {Path(path).name} » est protégé par un mot de passe.")


class WrongPassword(PdfError):
    def __init__(self, path):
        self.path = str(path)
        super().__init__(f"Mot de passe incorrect pour « {Path(path).name} ».")


# --------------------------------------------------------------------------
# Outils généraux
# --------------------------------------------------------------------------
def is_image(path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def is_pdf(path) -> bool:
    return Path(path).suffix.lower() == ".pdf"


def open_pdf(path, password: str | None = None) -> pymupdf.Document:
    """Ouvre un PDF depuis le disque (copie en mémoire) et l'authentifie."""
    path = str(path)
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise PdfError(f"Impossible de lire « {Path(path).name} » : {exc.strerror or exc}.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise PdfError(f"« {Path(path).name} » n'est pas un PDF lisible (fichier endommagé ou d'un autre format).")
    if doc.needs_pass:
        if not password:
            doc.close()
            raise PasswordRequired(path)
        if not doc.authenticate(password):
            doc.close()
            raise WrongPassword(path)
    if doc.page_count == 0:
        doc.close()
        raise PdfError(f"« {Path(path).name} » ne contient aucune page.")
    return doc


def needs_password(path) -> bool:
    try:
        with pymupdf.open(str(path)) as doc:
            return bool(doc.needs_pass)
    except Exception:
        return False


def check_password(path, password: str) -> bool:
    try:
        with pymupdf.open(str(path)) as doc:
            return bool(doc.authenticate(password)) if doc.needs_pass else True
    except Exception:
        return False


def pdf_info(path, password=None) -> dict:
    doc = open_pdf(path, password)
    info = {
        "pages": doc.page_count,
        "encrypted": bool(doc.is_encrypted) or bool(Path(path).exists() and needs_password(path)),
        "size": Path(path).stat().st_size,
        "title": (doc.metadata or {}).get("title") or "",
        "has_form": any(True for p in doc for _ in p.widgets()),
    }
    doc.close()
    return info


def _save(doc: pymupdf.Document, out, *, garbage=3, deflate=True, **kwargs) -> str:
    """Enregistre via un fichier temporaire puis remplace la cible."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".pdfceb-tmp")
    try:
        doc.save(str(tmp), garbage=garbage, deflate=deflate, **kwargs)
    finally:
        doc.close()
    os.replace(tmp, out)
    return str(out)


def _unique(path: Path) -> Path:
    """Renvoie un chemin libre (ajoute (2), (3)… si le fichier existe)."""
    if not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def parse_pages(spec: str, total: int, keep_order: bool = True) -> list[int]:
    """Analyse une sélection de pages saisie par l'utilisateur.

    Exemples : « 1-3, 5, 8- », « -4 », « fin », « pair », « impair ».
    Renvoie des indices commençant à 0, sans doublon.
    """
    if spec is None or not str(spec).strip():
        return list(range(total))
    result: list[int] = []
    seen = set()

    def add(i):
        if i not in seen:
            seen.add(i)
            result.append(i)

    tokens = [t for part in re.split(r"[,;]", str(spec)) for t in [part.strip().lower()] if t]
    for tok in tokens:
        tok = tok.replace(" ", "")
        if tok in ("tout", "toutes", "all"):
            for i in range(total):
                add(i)
            continue
        if tok in ("pair", "paires"):
            for i in range(1, total, 2):
                add(i)
            continue
        if tok in ("impair", "impaires"):
            for i in range(0, total, 2):
                add(i)
            continue
        tok = tok.replace("fin", str(total)).replace("end", str(total))
        m = re.fullmatch(r"(\d*)-(\d*)", tok)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else total
            if a < 1 or b < 1 or a > total or b > total:
                raise PdfError(f"La plage « {tok} » dépasse le nombre de pages ({total}).")
            step = 1 if b >= a else -1
            for p in range(a, b + step, step):
                add(p - 1)
            continue
        if tok.isdigit():
            p = int(tok)
            if p < 1 or p > total:
                raise PdfError(f"La page {p} n'existe pas (le document compte {total} pages).")
            add(p - 1)
            continue
        raise PdfError(f"Sélection de pages incompréhensible : « {tok} ». Exemple valide : 1-3, 5, 8-")
    if not keep_order:
        result.sort()
    return result


def parse_groups(spec: str, total: int) -> list[list[int]]:
    """« 1-3, 4-6, 9 » → [[0,1,2],[3,4,5],[8]] (une liste par fichier)."""
    groups = []
    for part in re.split(r"[,;]", spec or ""):
        part = part.strip()
        if part:
            groups.append(parse_pages(part, total))
    if not groups:
        raise PdfError("Indiquez au moins une plage de pages, par exemple : 1-3, 4-6.")
    return groups


def _font(bold: bool = False) -> pymupdf.Font:
    return pymupdf.Font("hebo" if bold else "helv")


def _hex_to_rgb(color) -> tuple:
    if color is None:
        return None
    if isinstance(color, (tuple, list)):
        vals = tuple(color[:3])
        return tuple(v / 255 for v in vals) if any(v > 1 for v in vals) else vals
    c = str(color).lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _rgb_to_hex(rgb) -> str:
    r, g, b = [max(0, min(255, round(v * 255))) for v in rgb]
    return f"#{r:02x}{g:02x}{b:02x}"


def _normalize_rotation(page: pymupdf.Page):
    """Supprime la rotation de la page en conservant son aspect.

    Après cet appel, les coordonnées de la page correspondent exactement
    à ce que l'utilisateur voit à l'écran.
    """
    if page.rotation:
        page.remove_rotation()
        # isole le contenu existant : sinon les ajouts ultérieurs (TextWriter)
        # hériteraient de la matrice de rotation compensatoire
        page.wrap_contents()


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------
def _image_frames(path):
    """Renvoie la liste des images (une par page pour les TIFF multipages)."""
    try:
        img = Image.open(path)
    except Exception:
        raise PdfError(f"Impossible de lire l'image « {Path(path).name} ».")
    frames = []
    for frame in ImageSequence.Iterator(img):
        fr = ImageOps.exif_transpose(frame.copy())
        frames.append(fr)
        if img.format in ("GIF", "WEBP"):
            break  # pas d'animation dans un PDF : première image seulement
    return img.format, img.info.get("dpi"), frames


def _image_bytes(frame: Image.Image, fmt_hint: str | None) -> bytes:
    """Encode une image pour l'insérer dans un PDF (JPEG pour les photos)."""
    if frame.mode in ("RGBA", "LA") or (frame.mode == "P" and "transparency" in frame.info):
        frame = frame.convert("RGBA")
        bg = Image.new("RGB", frame.size, (255, 255, 255))
        bg.paste(frame, mask=frame.split()[-1])
        frame = bg
    buf = io.BytesIO()
    if fmt_hint in ("JPEG", "MPO") or frame.mode in ("RGB", "CMYK") and fmt_hint in ("WEBP", "TIFF") and frame.width * frame.height > 250_000:
        if frame.mode not in ("RGB", "L"):
            frame = frame.convert("RGB")
        frame.save(buf, "JPEG", quality=93, optimize=True)
    else:
        if frame.mode not in ("RGB", "L", "1"):
            frame = frame.convert("RGB")
        frame.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _image_with_opacity(path_or_bytes, opacity: float = 1.0) -> bytes:
    """PNG avec transparence appliquée (pour filigranes et signatures)."""
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGBA")
    if opacity < 1:
        alpha = img.split()[-1].point(lambda a: int(a * max(0.0, opacity)))
        img.putalpha(alpha)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _add_image_page(doc, path, page_size="A4", orientation="auto", margin_mm=0.0):
    fmt, dpi, frames = _image_frames(path)
    for fr in frames:
        data = _image_bytes(fr, fmt)
        iw, ih = fr.size
        if page_size == "image":
            res = 96.0
            if dpi and dpi[0]:
                try:
                    res = float(dpi[0]) or 96.0
                except Exception:
                    res = 96.0
            w, h = iw * 72 / res, ih * 72 / res
            m = margin_mm * MM
            page = doc.new_page(width=w + 2 * m, height=h + 2 * m)
            rect = pymupdf.Rect(m, m, m + w, m + h)
        else:
            w, h = PAGE_SIZES.get(page_size, PAGE_SIZES["A4"])
            landscape = (orientation == "paysage") or (orientation == "auto" and iw > ih)
            if landscape:
                w, h = max(w, h), min(w, h)
            else:
                w, h = min(w, h), max(w, h)
            page = doc.new_page(width=w, height=h)
            m = margin_mm * MM
            rect = pymupdf.Rect(m, m, w - m, h - m)
        page.insert_image(rect, stream=data, keep_proportion=True)


def images_to_pdf(images, out, page_size="A4", orientation="auto", margin_mm=0.0) -> str:
    if not images:
        raise PdfError("Ajoutez au moins une image.")
    doc = pymupdf.open()
    for path in images:
        _add_image_page(doc, path, page_size, orientation, margin_mm)
    return _save(doc, out, garbage=4)


def images_to_pdfs(images, out_dir, page_size="A4", orientation="auto", margin_mm=0.0) -> list[str]:
    outs = []
    for path in images:
        doc = pymupdf.open()
        _add_image_page(doc, path, page_size, orientation, margin_mm)
        outs.append(_save(doc, _unique(Path(out_dir) / f"{Path(path).stem}.pdf"), garbage=4))
    return outs


def pdf_to_images(src, password, out_dir, fmt="jpg", dpi=150, pages=None, base=None) -> list[str]:
    doc = open_pdf(src, password)
    base = base or Path(src).stem
    idx = parse_pages(pages, doc.page_count) if isinstance(pages, str) else (pages or list(range(doc.page_count)))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outs = []
    width = len(str(doc.page_count))
    for i in idx:
        pix = doc[i].get_pixmap(dpi=int(dpi), alpha=False)
        target = _unique(out_dir / f"{base}_page_{str(i + 1).zfill(width)}.{fmt}")
        if fmt == "jpg":
            pix.save(str(target), jpg_quality=90)
        else:
            pix.save(str(target))
        outs.append(str(target))
    doc.close()
    return outs


def extract_images(src, password, out_dir, base=None, min_size=24) -> list[str]:
    """Extrait les images contenues dans le PDF, dans leur format d'origine."""
    doc = open_pdf(src, password)
    base = base or Path(src).stem
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outs, seen = [], set()
    n = 0
    for pno in range(doc.page_count):
        for img in doc.get_page_images(pno, full=True):
            xref, smask = img[0], img[1]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                if smask:
                    pix = pymupdf.Pixmap(doc, xref)
                    mask = pymupdf.Pixmap(doc, smask)
                    if pix.alpha:
                        pix = pymupdf.Pixmap(pix, 0)
                    if pix.colorspace and pix.colorspace.n > 3:
                        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                    pix = pymupdf.Pixmap(pix, mask)
                    if pix.width < min_size or pix.height < min_size:
                        continue
                    data, ext = pix.tobytes("png"), "png"
                else:
                    info = doc.extract_image(xref)
                    if not info or info["width"] < min_size or info["height"] < min_size:
                        continue
                    data, ext = info["image"], info["ext"]
                    if ext not in ("png", "jpg", "jpeg", "jpx", "bmp", "tiff", "gif"):
                        pix = pymupdf.Pixmap(doc, xref)
                        if pix.colorspace and pix.colorspace.n > 3:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        data, ext = pix.tobytes("png"), "png"
                    if ext == "jpx":
                        ext = "jp2"
            except Exception:
                continue
            n += 1
            target = _unique(out_dir / f"{base}_image_{n:03d}.{ext}")
            target.write_bytes(data)
            outs.append(str(target))
    doc.close()
    return outs


# --------------------------------------------------------------------------
# Organiser
# --------------------------------------------------------------------------
def merge(sources, out, bookmarks: bool = True) -> str:
    """Fusionne des PDF (et images) dans l'ordre donné.

    sources : liste de tuples (chemin, mot_de_passe).
    """
    if len(sources) < 1:
        raise PdfError("Ajoutez au moins deux fichiers à fusionner.")
    res = pymupdf.open()
    toc = []
    for path, pw in sources:
        start = res.page_count
        if is_image(path):
            _add_image_page(res, path, "A4", "auto", 0)
            if bookmarks:
                toc.append([1, Path(path).stem, start + 1])
            continue
        d = open_pdf(path, pw)
        res.insert_pdf(d)
        if bookmarks:
            toc.append([1, Path(path).stem, start + 1])
            for entry in d.get_toc(simple=True):
                lvl, title, pg = entry[0], entry[1], entry[2]
                toc.append([lvl + 1, title, (pg + start) if pg > 0 else start + 1])
        d.close()
    if bookmarks and toc:
        try:
            res.set_toc(toc)
        except Exception:
            res.set_toc([e for e in toc if e[0] == 1])
    return _save(res, out, garbage=4)


def split_groups(src, password, groups: list[list[int]], out_dir, base=None) -> list[str]:
    doc = open_pdf(src, password)
    base = base or Path(src).stem
    outs = []
    for g in groups:
        part = pymupdf.open()
        for i in g:
            part.insert_pdf(doc, from_page=i, to_page=i)
        label = f"{g[0] + 1}" if len(g) == 1 else f"{g[0] + 1}-{g[-1] + 1}"
        outs.append(_save(part, _unique(Path(out_dir) / f"{base}_pages_{label}.pdf"), garbage=4))
    doc.close()
    return outs


def split_every(src, password, n: int, out_dir, base=None) -> list[str]:
    n = max(1, int(n))
    doc = open_pdf(src, password)
    total = doc.page_count
    doc.close()
    groups = [list(range(i, min(i + n, total))) for i in range(0, total, n)]
    return split_groups(src, password, groups, out_dir, base)


def delete_pages(src, password, pages: list[int], out) -> str:
    doc = open_pdf(src, password)
    pages = sorted(set(pages))
    if not pages:
        doc.close()
        raise PdfError("Sélectionnez au moins une page à supprimer.")
    if len(pages) >= doc.page_count:
        doc.close()
        raise PdfError("Impossible de supprimer toutes les pages : le PDF serait vide.")
    doc.delete_pages(pages)
    return _save(doc, out, garbage=4)


def extract_pages(src, password, pages: list[int], out) -> str:
    if not pages:
        raise PdfError("Sélectionnez au moins une page à extraire.")
    doc = open_pdf(src, password)
    res = pymupdf.open()
    for i in pages:
        res.insert_pdf(doc, from_page=i, to_page=i)
    doc.close()
    return _save(res, out, garbage=4)


def organize(sources, items: list[dict], out) -> str:
    """Construit un PDF à partir d'une liste ordonnée de pages.

    sources : liste de (chemin, mot_de_passe)
    items   : {"src": i, "page": p, "rot": angle supplémentaire}
              ou {"blank": True, "width": w, "height": h}
    """
    if not items:
        raise PdfError("Le document final ne contient aucune page.")
    docs = [open_pdf(p, pw) for p, pw in sources]
    res = pymupdf.open()
    for it in items:
        if it.get("blank"):
            res.new_page(width=it.get("width", 595.28), height=it.get("height", 841.89))
            continue
        d = docs[it["src"]]
        p = it["page"]
        res.insert_pdf(d, from_page=p, to_page=p)
        extra = int(it.get("rot", 0)) % 360
        if extra:
            pg = res[-1]
            pg.set_rotation((pg.rotation + extra) % 360)
    for d in docs:
        d.close()
    return _save(res, out, garbage=4)


def rotate_pages(src, password, rotations: dict[int, int], out) -> str:
    """rotations : {indice_page: angle à ajouter (90, 180, 270)}."""
    doc = open_pdf(src, password)
    for i, angle in rotations.items():
        angle = int(angle) % 360
        if angle:
            page = doc[i]
            page.set_rotation((page.rotation + angle) % 360)
    return _save(doc, out)


# --------------------------------------------------------------------------
# Modifier : numéros, filigranes, rognage
# --------------------------------------------------------------------------
def add_page_numbers(src, password, out, *, position="bas-centre", fmt="{n}", pages=None,
                     first_number=1, font_size=11, margin_mm=10, color="#000000", bold=False,
                     total: int | None = None) -> str:
    """Ajoute une numérotation. fmt accepte {n} (numéro) et {total}."""
    doc = open_pdf(src, password)
    idx = parse_pages(pages, doc.page_count, keep_order=False) if isinstance(pages, str) or pages is None else sorted(pages)
    if total is None:
        total = first_number + len(idx) - 1
    font = _font(bold)
    rgb = _hex_to_rgb(color)
    vert, horiz = (position.split("-") + ["centre"])[:2]
    m = margin_mm * MM
    for k, i in enumerate(idx):
        page = doc[i]
        _normalize_rotation(page)
        text = fmt.replace("{n}", str(first_number + k)).replace("{total}", str(total))
        w = font.text_length(text, fontsize=font_size)
        r = page.rect
        if horiz == "gauche":
            x = r.x0 + m
        elif horiz == "droite":
            x = r.x1 - m - w
        else:
            x = (r.x0 + r.x1 - w) / 2
        y = (r.y0 + m + font_size * 0.8) if vert == "haut" else (r.y1 - m)
        tw = pymupdf.TextWriter(page.rect, color=rgb)
        tw.append((x, y), text, font=font, fontsize=font_size)
        tw.write_text(page)
    return _save(doc, out)


def add_text_watermark(src, password, out, *, text, font_size=60, color="#c0392b", opacity=0.25,
                       angle=45, mosaic=False, under=False, pages=None, bold=True) -> str:
    if not text.strip():
        raise PdfError("Saisissez le texte du filigrane.")
    doc = open_pdf(src, password)
    idx = parse_pages(pages, doc.page_count, keep_order=False) if isinstance(pages, str) or pages is None else sorted(pages)
    font = _font(bold)
    rgb = _hex_to_rgb(color)
    tw_len = font.text_length(text, fontsize=font_size)
    for i in idx:
        page = doc[i]
        _normalize_rotation(page)
        r = page.rect
        centers = []
        if mosaic:
            step_x = max(tw_len * 0.9, 120)
            step_y = max(font_size * 4, 120)
            y = r.y0 + step_y / 2
            row = 0
            while y < r.y1 + step_y:
                x = r.x0 + (step_x / 2 if row % 2 else 0)
                while x < r.x1 + step_x:
                    centers.append(pymupdf.Point(x, y))
                    x += step_x
                y += step_y
                row += 1
        else:
            centers.append(pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
        for c in centers:
            tw = pymupdf.TextWriter(page.rect, opacity=opacity, color=rgb)
            tw.append((c.x - tw_len / 2, c.y + font_size * 0.35), text, font=font, fontsize=font_size)
            tw.write_text(page, morph=(c, pymupdf.Matrix(angle)), overlay=not under)
    return _save(doc, out)


def add_image_watermark(src, password, out, *, image, scale=0.5, opacity=0.3, mosaic=False,
                        under=False, pages=None, position="centre") -> str:
    doc = open_pdf(src, password)
    idx = parse_pages(pages, doc.page_count, keep_order=False) if isinstance(pages, str) or pages is None else sorted(pages)
    data = _image_with_opacity(image, opacity)
    with Image.open(io.BytesIO(data)) as im:
        iw, ih = im.size
    ratio = ih / iw
    for i in idx:
        page = doc[i]
        _normalize_rotation(page)
        r = page.rect
        w = r.width * scale
        h = w * ratio
        rects = []
        if mosaic:
            gap = w * 0.4
            y = r.y0 + gap / 2
            while y < r.y1:
                x = r.x0 + gap / 2
                while x < r.x1:
                    rects.append(pymupdf.Rect(x, y, x + w, y + h))
                    x += w + gap
                y += h + gap
        else:
            cx = (r.x0 + r.x1) / 2
            cy = {"haut": r.y0 + h / 2 + 20, "bas": r.y1 - h / 2 - 20}.get(position, (r.y0 + r.y1) / 2)
            rects.append(pymupdf.Rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
        for rect in rects:
            page.insert_image(rect, stream=data, overlay=not under, keep_proportion=True)
    return _save(doc, out, garbage=4)


def _visible_to_cropbox(page: pymupdf.Page, visible: pymupdf.Rect) -> pymupdf.Rect:
    """Convertit un rectangle « tel qu'affiché » en coordonnées pour set_cropbox."""
    rr = visible * page.derotation_matrix
    rr.normalize()
    cb = page.cropbox
    return pymupdf.Rect(rr.x0 + cb.x0, rr.y0 + cb.y0, rr.x1 + cb.x0, rr.y1 + cb.y0)


def crop_margins(src, password, out, *, left=0.0, top=0.0, right=0.0, bottom=0.0, pages=None) -> str:
    """Rogne chaque page des marges indiquées (en mm), côté affichage."""
    doc = open_pdf(src, password)
    idx = parse_pages(pages, doc.page_count, keep_order=False) if isinstance(pages, str) or pages is None else sorted(pages)
    for i in idx:
        page = doc[i]
        r = page.rect
        vis = pymupdf.Rect(r.x0 + left * MM, r.y0 + top * MM, r.x1 - right * MM, r.y1 - bottom * MM)
        if vis.is_empty or vis.width < 20 or vis.height < 20:
            doc.close()
            raise PdfError("Les marges demandées sont plus grandes que la page.")
        page.set_cropbox(_visible_to_cropbox(page, vis) & page.mediabox)
    return _save(doc, out)


def crop_rect(src, password, out, rect_ratio, pages=None) -> str:
    """Rogne selon un rectangle exprimé en proportions de la page (0-1)."""
    x0, y0, x1, y1 = rect_ratio
    doc = open_pdf(src, password)
    idx = parse_pages(pages, doc.page_count, keep_order=False) if isinstance(pages, str) or pages is None else sorted(pages)
    for i in idx:
        page = doc[i]
        r = page.rect
        vis = pymupdf.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height, r.x0 + x1 * r.width, r.y0 + y1 * r.height)
        if vis.width < 10 or vis.height < 10:
            continue
        page.set_cropbox(_visible_to_cropbox(page, vis) & page.mediabox)
    return _save(doc, out)


def auto_crop(src, password, out, *, padding_mm=5.0, pages=None) -> str:
    """Supprime automatiquement les marges blanches de chaque page."""
    doc = open_pdf(src, password)
    idx = parse_pages(pages, doc.page_count, keep_order=False) if isinstance(pages, str) or pages is None else sorted(pages)
    for i in idx:
        page = doc[i]
        zoom = 1.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        mask = img.point(lambda v: 255 if v < 240 else 0)
        bbox = mask.getbbox()
        if not bbox:
            continue
        pad = padding_mm * MM
        r = page.rect
        vis = pymupdf.Rect(bbox[0] / zoom - pad, bbox[1] / zoom - pad, bbox[2] / zoom + pad, bbox[3] / zoom + pad) & r
        if vis.width < 20 or vis.height < 20:
            continue
        page.set_cropbox(_visible_to_cropbox(page, vis) & page.mediabox)
    return _save(doc, out)


# --------------------------------------------------------------------------
# Optimiser
# --------------------------------------------------------------------------
COMPRESSION_LEVELS = {
    "faible": None,
    "recommandée": dict(dpi_threshold=200, dpi_target=150, quality=75),
    "forte": dict(dpi_threshold=110, dpi_target=96, quality=55),
}


def compress(src, password, out, level="recommandée") -> tuple[int, int]:
    """Compresse le PDF. Renvoie (taille_avant, taille_après) en octets."""
    before = Path(src).stat().st_size
    doc = open_pdf(src, password)
    params = COMPRESSION_LEVELS.get(level)
    if params:
        try:
            doc.rewrite_images(**params)
        except Exception:
            pass
    try:
        doc.subset_fonts()
    except Exception:
        pass
    kw = dict(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True, use_objstms=1)
    if doc.is_encrypted and password:
        kw.update(encryption=pymupdf.PDF_ENCRYPT_KEEP)
    out_path = Path(out)
    _save(doc, out_path, **kw)
    after = out_path.stat().st_size
    if after >= before and Path(src).resolve() != out_path.resolve():
        # la compression n'apporte rien : on conserve le fichier d'origine
        out_path.write_bytes(Path(src).read_bytes())
        after = before
    return before, after


def repair(src, password, out) -> bool:
    """Reconstruit la structure du PDF. Renvoie True si des erreurs ont été corrigées."""
    path = str(src)
    try:
        data = Path(path).read_bytes()
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise PdfError("Ce fichier est trop endommagé pour être réparé.")
    if doc.needs_pass:
        if not password:
            raise PasswordRequired(path)
        if not doc.authenticate(password):
            raise WrongPassword(path)
    repaired = bool(getattr(doc, "is_repaired", False))
    # Reconstruction page par page dans un document neuf
    res = pymupdf.open()
    bad = 0
    for i in range(doc.page_count):
        try:
            res.insert_pdf(doc, from_page=i, to_page=i)
        except Exception:
            bad += 1
    if res.page_count == 0:
        raise PdfError("Aucune page n'a pu être récupérée dans ce fichier.")
    try:
        res.set_toc(doc.get_toc())
    except Exception:
        pass
    try:
        res.set_metadata(doc.metadata or {})
    except Exception:
        pass
    doc.close()
    _save(res, out, garbage=4, clean=True)
    return repaired or bad > 0


# --------------------------------------------------------------------------
# Sécurité
# --------------------------------------------------------------------------
def protect(src, password, out, *, user_pw: str, owner_pw: str | None = None, allow_print=True,
            allow_copy=True, allow_modify=False, allow_annotate=True) -> str:
    if not user_pw:
        raise PdfError("Saisissez un mot de passe.")
    doc = open_pdf(src, password)
    perms = pymupdf.PDF_PERM_ACCESSIBILITY
    if allow_print:
        perms |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    if allow_copy:
        perms |= pymupdf.PDF_PERM_COPY
    if allow_modify:
        perms |= pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ASSEMBLE
    if allow_annotate:
        perms |= pymupdf.PDF_PERM_ANNOTATE | pymupdf.PDF_PERM_FORM
    owner = owner_pw or (user_pw + "-" + secrets.token_urlsafe(12))
    return _save(doc, out, garbage=3, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                 user_pw=user_pw, owner_pw=owner, permissions=perms)


def unlock(src, password, out) -> str:
    doc = open_pdf(src, password)
    return _save(doc, out, garbage=3, encryption=pymupdf.PDF_ENCRYPT_NONE)


# --------------------------------------------------------------------------
# Formulaires
# --------------------------------------------------------------------------
_WTYPES = {
    pymupdf.PDF_WIDGET_TYPE_TEXT: "texte",
    pymupdf.PDF_WIDGET_TYPE_CHECKBOX: "case",
    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
    pymupdf.PDF_WIDGET_TYPE_COMBOBOX: "liste",
    pymupdf.PDF_WIDGET_TYPE_LISTBOX: "liste",
}


def _radio_state(w) -> str:
    try:
        st = w.on_state()
    except Exception:
        st = None
    if st in (None, False, True, "", "Off"):
        st = w.button_caption or f"option_{w.xref}"
    return str(st)


def get_form_fields(src, password=None) -> list[dict]:
    doc = open_pdf(src, password)
    fields: dict[str, dict] = {}
    for page in doc:
        for w in page.widgets():
            kind = _WTYPES.get(w.field_type)
            if not kind or not w.field_name:
                continue
            f = fields.get(w.field_name)
            if f is None:
                f = fields[w.field_name] = {
                    "name": w.field_name,
                    "label": (w.field_label or w.field_name).strip(),
                    "type": kind,
                    "value": None,
                    "options": [],
                    "page": page.number + 1,
                    "readonly": bool(w.field_flags & 1),
                }
            if kind == "texte":
                f["value"] = w.field_value or ""
                f["multiline"] = bool(w.field_flags & (1 << 12))
            elif kind == "case":
                f["value"] = w.field_value not in (None, False, "Off", "")
            elif kind == "radio":
                st = _radio_state(w)
                f["options"].append(st)
                if w.field_value not in (None, False, "Off", "", "None"):
                    f["value"] = st
            elif kind == "liste":
                f["options"] = list(w.choice_values or [])
                f["value"] = w.field_value
                if isinstance(f["value"], (list, tuple)):
                    f["value"] = f["value"][0] if f["value"] else None
                f["options"] = [o[1] if isinstance(o, (list, tuple)) else o for o in f["options"]]
    doc.close()
    return list(fields.values())


def fill_form(src, password, out, values: dict, flatten=False) -> str:
    doc = open_pdf(src, password)
    for page in doc:
        for w in page.widgets():
            name = w.field_name
            if name not in values:
                continue
            v = values[name]
            kind = _WTYPES.get(w.field_type)
            try:
                if kind == "texte":
                    w.field_value = "" if v is None else str(v)
                elif kind == "case":
                    w.field_value = w.on_state() if v else "Off"
                elif kind == "radio":
                    w.field_value = (_radio_state(w) == v)
                elif kind == "liste":
                    w.field_value = "" if v is None else str(v)
                w.update()
            except Exception:
                continue
    if flatten:
        doc.bake(annots=False, widgets=True)
    return _save(doc, out)


# --------------------------------------------------------------------------
# Comparer
# --------------------------------------------------------------------------
def _words(doc):
    """Mots dans l'ordre de lecture, avec leur position telle qu'affichée."""
    out = []
    for page in doc:
        rot = page.rotation_matrix
        # le tri se fait dans le repère non tourné, où le texte est horizontal
        for w in page.get_text("words", sort=True):
            r = pymupdf.Rect(w[:4]) * rot
            r.normalize()
            out.append((page.number, r, w[4]))
    return out


def compare(src_a, pw_a, src_b, pw_b, out_report) -> dict:
    """Compare le texte de deux PDF et produit un rapport visuel.

    Le rapport contient une synthèse des différences, puis les pages côte à
    côte (original à gauche, nouvelle version à droite) avec les mots
    supprimés surlignés en rouge et les mots ajoutés en vert.
    """
    da, db = open_pdf(src_a, pw_a), open_pdf(src_b, pw_b)
    wa, wb = _words(da), _words(db)
    ta = [w[2] for w in wa]
    tb = [w[2] for w in wb]
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=(len(ta) + len(tb) > 40000))
    marks_a: dict[int, list] = {}
    marks_b: dict[int, list] = {}
    changes = []
    added = removed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            removed += i2 - i1
            for k in range(i1, i2):
                marks_a.setdefault(wa[k][0], []).append(wa[k][1])
        if j2 > j1:
            added += j2 - j1
            for k in range(j1, j2):
                marks_b.setdefault(wb[k][0], []).append(wb[k][1])
        changes.append({
            "type": {"replace": "modifié", "delete": "supprimé", "insert": "ajouté"}[tag],
            "old": " ".join(ta[i1:i2]),
            "new": " ".join(tb[j1:j2]),
            "page_a": (wa[i1][0] + 1) if i2 > i1 else None,
            "page_b": (wb[j1][0] + 1) if j2 > j1 else None,
        })

    report = pymupdf.open()
    name_a, name_b = Path(src_a).name, Path(src_b).name
    # --- synthèse
    css = ("* {font-family: sans-serif; font-size: 10px; color: #222;} h1 {font-size: 18px; color:#111;}"
           " .del {background-color: #ffd6d6; color:#a40000;} .add {background-color: #d6f5d6; color:#0a6b0a;}"
           " p {margin: 0 0 6px 0;} .meta {color:#666;}")
    head = (f"<h1>Comparaison de documents</h1><p class='meta'>Original : <b>{html.escape(name_a)}</b> "
            f"({da.page_count} p.)<br>Nouvelle version : <b>{html.escape(name_b)}</b> ({db.page_count} p.)</p>")
    if not changes:
        head += "<p><b>Aucune différence de texte n'a été trouvée.</b></p>"
    else:
        head += (f"<p><b>{len(changes)} différence(s)</b> — {removed} mot(s) supprimé(s) ou remplacé(s), "
                 f"{added} mot(s) ajouté(s) ou nouveaux.</p>")
    blocks = []
    for n, c in enumerate(changes, 1):
        old = html.escape(c["old"][:400] + ("…" if len(c["old"]) > 400 else ""))
        new = html.escape(c["new"][:400] + ("…" if len(c["new"]) > 400 else ""))
        where = []
        if c["page_a"]:
            where.append(f"p. {c['page_a']} de l'original")
        if c["page_b"]:
            where.append(f"p. {c['page_b']} de la nouvelle version")
        line = f"<p><b>{n}. {c['type'].capitalize()}</b> <span class='meta'>({', '.join(where)})</span><br>"
        if old:
            line += f"<span class='del'>− {old}</span>"
        if old and new:
            line += "<br>"
        if new:
            line += f"<span class='add'>+ {new}</span>"
        blocks.append(line + "</p>")
    w, h = PAGE_SIZES["A4"]
    pending = [head] + blocks
    while pending:
        page = report.new_page(width=w, height=h)
        chunk = []
        size = 0
        while pending and (size + len(pending[0]) < 3800 or not chunk):
            size += len(pending[0])
            chunk.append(pending.pop(0))
        page.insert_htmlbox(pymupdf.Rect(40, 40, w - 40, h - 40), "".join(chunk), css=css)

    # --- pages côte à côte
    gap, header = 24, 28
    for i in range(max(da.page_count, db.page_count)):
        ra = da[i].rect if i < da.page_count else None
        rb = db[i].rect if i < db.page_count else None
        wa_ = ra.width if ra else (rb.width if rb else 595)
        wb_ = rb.width if rb else wa_
        hh = max(ra.height if ra else 0, rb.height if rb else 0)
        page = report.new_page(width=wa_ + wb_ + gap * 3, height=hh + header + gap)
        font = _font(True)
        tw = pymupdf.TextWriter(page.rect, color=(0.3, 0.3, 0.3))
        tw.append((gap, 20), f"Original — page {i + 1}" if ra else "Original — (pas de page)", font=font, fontsize=11)
        tw.append((gap * 2 + wa_, 20), f"Nouvelle version — page {i + 1}" if rb else "Nouvelle version — (pas de page)", font=font, fontsize=11)
        tw.write_text(page)
        if ra:
            ta_rect = pymupdf.Rect(gap, header, gap + ra.width, header + ra.height)
            page.draw_rect(ta_rect, color=(0.8, 0.8, 0.8), width=0.5)
            page.show_pdf_page(ta_rect, da, i)
            for r in marks_a.get(i, []):
                page.draw_rect(r + (ta_rect.x0, ta_rect.y0, ta_rect.x0, ta_rect.y0), color=None,
                               fill=(0.95, 0.2, 0.2), fill_opacity=0.35)
        if rb:
            x0 = gap * 2 + wa_
            tb_rect = pymupdf.Rect(x0, header, x0 + rb.width, header + rb.height)
            page.draw_rect(tb_rect, color=(0.8, 0.8, 0.8), width=0.5)
            page.show_pdf_page(tb_rect, db, i)
            for r in marks_b.get(i, []):
                page.draw_rect(r + (tb_rect.x0, tb_rect.y0, tb_rect.x0, tb_rect.y0), color=None,
                               fill=(0.2, 0.75, 0.2), fill_opacity=0.35)
    da.close()
    db.close()
    _save(report, out_report, garbage=4)
    return {"changes": changes, "added": added, "removed": removed, "identical": not changes}


# --------------------------------------------------------------------------
# Éditeur : application des modifications
# --------------------------------------------------------------------------
_CSS_FAMILY = {"sans": "sans-serif", "serif": "serif", "mono": "monospace"}


def _text_html(item) -> tuple[str, str]:
    family = _CSS_FAMILY.get(item.get("font", "sans"), "sans-serif")
    size = float(item.get("size", 12))
    color = item.get("color", "#000000")
    weight = "bold" if item.get("bold") else "normal"
    style = "italic" if item.get("italic") else "normal"
    align = item.get("align", "left")
    css = (f"* {{font-family: {family}; font-size: {size}px; color: {color}; font-weight: {weight};"
           f" font-style: {style}; line-height: 1.15; margin: 0; padding: 0; text-align: {align};}}")
    lines = item.get("text", "").split("\n")
    body = "<br>".join(html.escape(l).replace("  ", "&nbsp; ") or "&nbsp;" for l in lines)
    return f"<div>{body}</div>", css


def apply_edits(src, password, out, edits: dict, *, scrub_metadata=False) -> str:
    """Applique les éléments ajoutés dans l'éditeur.

    edits : {indice_page: [élément, ...]} ; chaque élément est un dict avec
    une clé « type » parmi : text, image, rect, ellipse, line, arrow, ink,
    highlight, whiteout, redact, note. Les coordonnées sont en points,
    dans le repère de la page telle qu'affichée.
    """
    doc = open_pdf(src, password)
    any_redact = False
    for pno, items in edits.items():
        if not items:
            continue
        page = doc[int(pno)]
        _normalize_rotation(page)
        # 1) caviardage d'abord, pour ne pas effacer les ajouts
        redacts = [it for it in items if it["type"] == "redact"]
        if redacts:
            any_redact = True
            for it in redacts:
                page.add_redact_annot(pymupdf.Rect(it["rect"]), fill=(0, 0, 0), cross_out=False)
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                                  graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                                  text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        # 2) autres éléments, dans l'ordre d'empilement
        for it in items:
            t = it["type"]
            if t == "redact":
                continue
            op = float(it.get("opacity", 1.0))
            if t in ("rect", "ellipse", "whiteout"):
                rect = pymupdf.Rect(it["rect"])
                if t == "whiteout":
                    page.draw_rect(rect, color=None, fill=(1, 1, 1), width=0)
                    continue
                stroke = _hex_to_rgb(it.get("stroke")) if it.get("stroke") else None
                fill = _hex_to_rgb(it.get("fill")) if it.get("fill") else None
                width = float(it.get("width", 1.5)) if stroke else 0
                fn = page.draw_rect if t == "rect" else page.draw_oval
                fn(rect, color=stroke, fill=fill, width=width, stroke_opacity=op, fill_opacity=op)
            elif t in ("line", "arrow"):
                p1, p2 = pymupdf.Point(it["p1"]), pymupdf.Point(it["p2"])
                col = _hex_to_rgb(it.get("stroke", "#000000"))
                width = float(it.get("width", 1.5))
                page.draw_line(p1, p2, color=col, width=width, lineCap=1, stroke_opacity=op)
                if t == "arrow":
                    ang = math.atan2(p2.y - p1.y, p2.x - p1.x)
                    L = max(8.0, width * 4)
                    left = pymupdf.Point(p2.x - L * math.cos(ang - 0.45), p2.y - L * math.sin(ang - 0.45))
                    right = pymupdf.Point(p2.x - L * math.cos(ang + 0.45), p2.y - L * math.sin(ang + 0.45))
                    page.draw_polyline([left, p2, right], color=col, fill=col, width=width,
                                       closePath=True, stroke_opacity=op, fill_opacity=op)
            elif t == "ink":
                col = _hex_to_rgb(it.get("stroke", "#000000"))
                width = float(it.get("width", 2))
                for stroke in it.get("strokes", []):
                    pts = [pymupdf.Point(p) for p in stroke]
                    if len(pts) == 1:
                        pts.append(pts[0] + (0.1, 0.1))
                    if len(pts) >= 2:
                        page.draw_polyline(pts, color=col, width=width, lineCap=1, lineJoin=1, stroke_opacity=op)
            elif t == "image":
                data = it.get("data")
                if data is None and it.get("path"):
                    data = Path(it["path"]).read_bytes()
                if op < 1 or it.get("force_png"):
                    data = _image_with_opacity(data, op)
                page.insert_image(pymupdf.Rect(it["rect"]), stream=data, keep_proportion=False)
            elif t == "text":
                if not it.get("text", "").strip():
                    continue
                body, css = _text_html(it)
                r = pymupdf.Rect(it["rect"])
                # marge de sécurité : les métriques de police diffèrent légèrement
                r = pymupdf.Rect(r.x0, r.y0, r.x1 + max(4, r.width * 0.06), r.y1 + r.height + 40)
                page.insert_htmlbox(r, body, css=css, scale_low=1, opacity=op)
            elif t == "highlight":
                annot = page.add_highlight_annot(pymupdf.Rect(it["rect"]))
                annot.set_colors(stroke=_hex_to_rgb(it.get("color", "#ffeb3b")))
                annot.update()
            elif t == "note":
                annot = page.add_text_annot(pymupdf.Point(it["point"]), it.get("text", ""), icon="Comment")
                annot.set_info(title=it.get("author", "PDF Ceb"))
                annot.update()
    if any_redact and scrub_metadata:
        try:
            doc.scrub(attached_files=False, clean_pages=False, embedded_files=False, hidden_text=False,
                      javascript=True, metadata=True, redactions=False, remove_links=False,
                      reset_fields=False, reset_responses=False, thumbnails=True, xml_metadata=True)
        except Exception:
            doc.set_metadata({})
    return _save(doc, out, garbage=4, clean=True)


def search_text_rects(src, password, term: str) -> dict[int, list[tuple]]:
    """Cherche un texte (sans tenir compte de la casse) dans tout le document."""
    term = term.strip()
    if not term:
        return {}
    doc = open_pdf(src, password)
    found = {}
    for page in doc:
        rot = page.rotation_matrix
        rects = page.search_for(term)
        if rects:
            # coordonnées dans le repère affiché (page éventuellement tournée)
            vis = []
            for r in rects:
                rr = r * rot
                rr.normalize()
                vis.append(tuple(rr))
            found[page.number] = vis
    doc.close()
    return found
