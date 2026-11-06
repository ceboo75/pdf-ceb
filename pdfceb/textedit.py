"""Modification du texte existant d'un PDF.

Principe :
1. analyse de la page : paragraphes → lignes → caractères, avec pour chaque
   caractère sa police, sa taille, sa couleur et sa position exacte ;
2. suppression des seuls caractères modifiés (aucun rectangle n'est posé :
   le fond, les cadres et les images restent intacts) ;
3. réécriture du nouveau texte sur les mêmes lignes de base, dans la même
   police (reconnue sur l'ordinateur ou reprise du PDF), avec l'alignement
   d'origine (gauche, centré, droite, justifié) et le même interlignage.

Les caractères inchangés en début de ligne et les lignes inchangées ne sont
pas touchés, ce qui rend la modification indécelable à l'œil.

Les coordonnées sont celles de la page telle qu'affichée : l'appelant doit
avoir supprimé l'éventuelle rotation de la page (voir core._normalize_rotation).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import pymupdf

from . import fontmatch


# --------------------------------------------------------------------------
# Structures
# --------------------------------------------------------------------------
@dataclass
class Style:
    key: str
    font: str
    size: float
    color: int
    flags: int
    ascender: float
    descender: float
    embedded: bytes | None = None

    @property
    def rgb(self):
        c = self.color
        return ((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255

    @property
    def hex(self):
        return f"#{self.color & 0xFFFFFF:06x}"

    @property
    def bold(self):
        return bool(self.flags & 16) or "bold" in self.font.lower()

    @property
    def italic(self):
        return bool(self.flags & 2) or "italic" in self.font.lower() or "oblique" in self.font.lower()


@dataclass
class Char:
    c: str
    style: str
    x0: float
    x1: float
    ox: float   # origine (abscisse de départ du glyphe)
    oy: float   # ligne de base
    size: float


@dataclass
class Line:
    chars: list[Char]
    baseline: float
    bbox: tuple

    @property
    def text(self):
        return "".join(c.c for c in self.chars)

    @property
    def left(self):
        return self.chars[0].ox if self.chars else self.bbox[0]

    @property
    def right(self):
        visible = [c for c in self.chars if not c.c.isspace()]
        return visible[-1].x1 if visible else self.bbox[2]

    def runs(self):
        out = []
        for ch in self.chars:
            if out and out[-1][1] == ch.style:
                out[-1][0] += ch.c
            else:
                out.append([ch.c, ch.style])
        return [tuple(r) for r in out]


@dataclass
class Paragraph:
    key: str
    lines: list[Line]
    align: str = "left"
    left: float = 0.0
    right: float = 0.0
    indent: float = 0.0
    pitch: float = 0.0
    limit: float = 0.0   # bord droit utilisable (colonne) pour un texte non justifié

    @property
    def bbox(self):
        x0 = min(l.bbox[0] for l in self.lines)
        y0 = min(l.bbox[1] for l in self.lines)
        x1 = max(l.bbox[2] for l in self.lines)
        y1 = max(l.bbox[3] for l in self.lines)
        return (x0, y0, x1, y1)

    def _hard_break(self, prev: "Line", nxt: "Line") -> bool:
        """Vrai si le passage à la ligne était voulu (fin de paragraphe, retour forcé)."""
        words = nxt.text.lstrip().split(" ")
        first = words[0] if words else ""
        chars = [c for c in nxt.chars if not c.c.isspace()][:max(1, len(first))]
        first_w = (chars[-1].x1 - chars[0].x0) if chars else 0.0
        size = statistics.median(c.size for c in prev.chars)
        remaining = self.right - prev.right - 0.3 * size
        if first_w and first_w < remaining - 1:
            return True  # le mot suivant aurait tenu : retour à la ligne volontaire
        ended = prev.text.rstrip().endswith((".", ":", "!", "?", ";", "\u00bb"))
        starts = bool(first) and (first[0].isupper() or first[0].isdigit() or first[0] in "-\u2022\u2013")
        return self.align != "justify" and ended and starts

    def runs(self, overrides: dict | None = None):
        """Texte du paragraphe sous forme de runs ; les retours voulus deviennent « \\n ».

        overrides : {indice de ligne: runs} pour tenir compte de lignes déjà modifiées.
        """
        out: list[list] = []
        overrides = overrides or {}
        for i, line in enumerate(self.lines):
            rs = [list(r) for r in (overrides[i] if i in overrides else line.runs())]
            if i in overrides and not rs:
                continue
            if i > 0:
                prev = self.lines[i - 1]
                prev_text = out[-1][0] if out else ""
                if rs and self._hard_break(prev, line):
                    rs[0][0] = "\n" + rs[0][0].lstrip()  # fin de paragraphe probable
                elif rs and not prev_text.endswith((" ", "-", "\u00ad")) and not rs[0][0].startswith(" "):
                    rs[0][0] = " " + rs[0][0]
                elif prev_text.endswith("\u00ad"):
                    out[-1][0] = prev_text[:-1]
            for r in rs:
                if out and out[-1][1] == r[1]:
                    out[-1][0] += r[0]
                else:
                    out.append(r)
        return [tuple(r) for r in out]


@dataclass
class PageText:
    paragraphs: list[Paragraph]
    styles: dict[str, Style]
    page_width: float = 0.0
    text_right: float = 0.0   # marge droite du texte de la page

    def find(self, key) -> Paragraph | None:
        return next((p for p in self.paragraphs if p.key == key), None)

    def line_at(self, x, y):
        """(paragraphe, indice de ligne) sous le point, ou (None, None)."""
        best = None
        for p in self.paragraphs:
            for i, l in enumerate(p.lines):
                x0, y0, x1, y1 = l.bbox
                if x0 - 2 <= x <= x1 + 2 and y0 - 1 <= y <= y1 + 1:
                    d = abs((y0 + y1) / 2 - y)
                    if best is None or d < best[0]:
                        best = (d, p, i)
        return (best[1], best[2]) if best else (None, None)


# --------------------------------------------------------------------------
# Analyse
# --------------------------------------------------------------------------
def _style_key(span) -> str:
    return f"{span['font']}|{round(span['size'], 2)}|{span['color']}|{span['flags']}"


def _embedded_fonts(page: pymupdf.Page) -> dict[str, bytes]:
    out = {}
    try:
        for f in page.get_fonts(full=True):
            xref, basefont = f[0], f[3]
            try:
                name, ext, typ, buf = page.parent.extract_font(xref)
            except Exception:
                continue
            if buf:
                out[fontmatch.norm(fontmatch.strip_subset(basefont))] = buf
    except Exception:
        pass
    return out


def analyze(page: pymupdf.Page) -> PageText:
    """Reconstitue les lignes et paragraphes de la page à partir de la géométrie.

    On ne se fie pas à l'ordre du contenu du PDF (souvent morcelé) : les
    fragments sont regroupés en lignes visuelles (même ligne de base, contigus),
    puis les lignes en paragraphes (interlignage régulier, même colonne, même
    taille de police).
    """
    raw = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP)
    embedded = _embedded_fonts(page)
    styles: dict[str, Style] = {}
    frags: list[Line] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for l in block.get("lines", []):
            d = l.get("dir", (1, 0))
            if abs(d[0] - 1) > 0.01 or abs(d[1]) > 0.01 or l.get("wmode", 0):
                continue  # texte tourné ou vertical : non modifiable
            chars = []
            for sp in l["spans"]:
                key = _style_key(sp)
                if key not in styles:
                    emb = embedded.get(fontmatch.norm(fontmatch.strip_subset(sp["font"])))
                    styles[key] = Style(key, sp["font"], sp["size"], sp["color"], sp["flags"],
                                        sp.get("ascender", 0.9), sp.get("descender", -0.2), emb)
                for ch in sp["chars"]:
                    x0, y0, x1, y1 = ch["bbox"]
                    chars.append(Char(ch["c"], key, x0, x1, ch["origin"][0], ch["origin"][1], sp["size"]))
            if not chars or not "".join(c.c for c in chars).strip():
                continue
            base = statistics.median(c.oy for c in chars)
            frags.append(Line(chars, base, tuple(l["bbox"])))

    # 1) fragments -> lignes visuelles
    frags.sort(key=lambda f: (round(f.baseline, 1), f.bbox[0]))
    lines: list[Line] = []
    for f in frags:
        size = max(c.size for c in f.chars)
        merged = False
        for ln in reversed(lines[-8:]):
            if abs(ln.baseline - f.baseline) > 0.25 * size:
                continue
            gap = f.bbox[0] - ln.bbox[2]
            if -0.5 * size <= gap <= 0.9 * size:
                ln.chars.extend(f.chars)
                ln.bbox = (min(ln.bbox[0], f.bbox[0]), min(ln.bbox[1], f.bbox[1]),
                           max(ln.bbox[2], f.bbox[2]), max(ln.bbox[3], f.bbox[3]))
                merged = True
                break
        if not merged:
            lines.append(Line(list(f.chars), f.baseline, f.bbox))
    for ln in lines:
        ln.chars.sort(key=lambda c: c.ox)
        ln.baseline = statistics.median(c.oy for c in ln.chars)

    # 2) lignes -> paragraphes : une ligne rejoint le paragraphe situé juste
    #    au-dessus, dans la même colonne, avec la même taille de caractères
    lines.sort(key=lambda l: (l.baseline, l.bbox[0]))
    groups: list[list[Line]] = []
    for ln in lines:
        size = statistics.median(c.size for c in ln.chars)
        best = None
        for g in groups:
            last = g[-1]
            lsize = statistics.median(c.size for c in last.chars)
            delta = ln.baseline - last.baseline
            if abs(size - lsize) > 0.2 * lsize or delta < 0.6 * size:
                continue
            pitches = [b.baseline - a.baseline for a, b in zip(g, g[1:])]
            if pitches:
                ref = statistics.median(pitches)
                if abs(delta - ref) > max(0.15 * ref, 1.0):
                    continue
            elif delta > 1.75 * max(size, lsize):
                continue
            gx0 = min(l.bbox[0] for l in g)
            gx1 = max(l.bbox[2] for l in g)
            overlap = min(ln.bbox[2], gx1) - max(ln.bbox[0], gx0)
            if overlap < 0.3 * min(ln.bbox[2] - ln.bbox[0], last.bbox[2] - last.bbox[0]):
                continue
            if best is None or delta < best[0]:
                best = (delta, g)
        if best:
            best[1].append(ln)
        else:
            groups.append([ln])
    groups.sort(key=lambda g: (g[0].baseline, g[0].bbox[0]))
    paragraphs = [_make_paragraph(f"p{i}", g, page.rect.width) for i, g in enumerate(groups)]
    text_right = max((l.right for l in lines), default=page.rect.width)
    for p in paragraphs:
        x0, y0, x1, y1 = p.bbox
        limit = max(text_right, x1)
        for q in paragraphs:
            if q is p:
                continue
            qx0, qy0, qx1, qy1 = q.bbox
            if qx0 >= x1 - 1 and qy0 < y1 and qy1 > y0:   # texte à droite, à la même hauteur
                limit = min(limit, qx0 - 6)
        p.limit = max(limit, x1)
    return PageText(paragraphs, styles, page.rect.width, text_right)


def _make_paragraph(key, lines: list[Line], page_width) -> Paragraph:
    p = Paragraph(key, lines)
    lefts = [l.left for l in lines]
    rights = [l.right for l in lines]
    size = statistics.median(c.size for l in lines for c in l.chars)
    tol = max(1.0, size * 0.12)
    p.left = min(lefts[1:]) if len(lines) > 1 else lefts[0]
    p.indent = lefts[0] - p.left if len(lines) > 1 else 0.0
    p.right = max(rights)
    pitches = [b.baseline - a.baseline for a, b in zip(lines, lines[1:])]
    p.pitch = statistics.median(pitches) if pitches else size * 1.2
    if len(lines) >= 2:
        left_ok = all(abs(x - p.left) <= tol for x in lefts[1:])
        right_body = rights[:-1]
        right_ok = all(abs(x - max(right_body)) <= tol for x in right_body)
        centers = [(a + b) / 2 for a, b in zip(lefts, rights)]
        center_ok = all(abs(c - centers[0]) <= tol for c in centers)
        if left_ok and right_ok:
            # justifié si les lignes pleines s'arrêtent toutes au même endroit et
            # qu'au moins une a des espaces élargies
            p.align = "justify" if _has_stretched_spaces(lines[:-1]) else "left"
            if p.align == "justify":
                p.right = max(right_body)
        elif center_ok and not left_ok:
            p.align = "center"
        elif all(abs(x - max(rights)) <= tol for x in rights) and not left_ok:
            p.align = "right"
        else:
            p.align = "left"
    else:
        l = lines[0]
        center = (l.left + l.right) / 2
        if abs(center - page_width / 2) < max(2.0, size * 0.3) and l.left > page_width * 0.15:
            p.align = "center"
        else:
            p.align = "left"
    return p


def _has_stretched_spaces(lines: list[Line]) -> bool:
    """Vrai si les espaces sont plus larges que la normale (texte justifié)."""
    widths = []
    for l in lines:
        for a, b in zip(l.chars, l.chars[1:]):
            if a.c == " ":
                widths.append((b.ox - a.ox) / max(a.size, 1))
    if len(widths) < 2:
        return False
    return statistics.pstdev(widths) > 0.02 or statistics.mean(widths) > 0.32


# --------------------------------------------------------------------------
# Mise en page du nouveau texte
# --------------------------------------------------------------------------
@dataclass
class Placed:
    c: str
    style: str
    x: float
    y: float
    size: float


class FontBook:
    """Police résolue pour chaque style, en tenant compte de tous les caractères à écrire."""

    def __init__(self, styles: dict[str, Style]):
        self.styles = styles
        self.need: dict[str, set] = {k: {" "} for k in styles}
        self.res: dict[str, fontmatch.ResolvedFont] = {}
        self.notes: set[str] = set()

    def need_text(self, style_key: str, text: str):
        cur = self.need.setdefault(style_key, {" "})
        new = set(text) - cur - {"\n"}
        if new:
            cur |= new
            self.res.pop(style_key, None)

    def font(self, style_key: str) -> fontmatch.ResolvedFont:
        r = self.res.get(style_key)
        if r is None:
            st = self.styles[style_key]
            r = fontmatch.resolve(st.font, st.flags, "".join(sorted(self.need[style_key])), st.embedded)
            self.res[style_key] = r
        return r

    def collect_notes(self, keys):
        for k in keys:
            n = self.font(k).note
            if n:
                self.notes.add(n)


def _spacing(line: Line, book: FontBook) -> tuple[float, float]:
    """Estime l'espacement des caractères et des mots de la ligne d'origine."""
    cs, ws = [], []
    for a, b in zip(line.chars, line.chars[1:]):
        if a.style != b.style or abs(a.oy - b.oy) > 0.5:
            continue
        st = book.styles[a.style]
        rf = book.font(a.style)
        if not rf.exact:
            continue
        metric = rf.font.text_length(a.c, fontsize=st.size)
        (ws if a.c == " " else cs).append((b.ox - a.ox) - metric)
    c = statistics.median(cs) if len(cs) >= 3 else 0.0
    w = statistics.median(ws) if ws else 0.0
    c = max(-1.0, min(2.0, c)) if abs(c) > 0.05 else 0.0
    return c, w - c


def _measure(chars: list[tuple[str, str]], book: FontBook, cs: float, ws: float) -> list[float]:
    out = []
    for ch, sk in chars:
        st = book.styles[sk]
        f = book.font(sk).font
        w = f.text_length(ch, fontsize=st.size) + cs
        if ch == " ":
            w += ws
        out.append(w)
    return out


def layout(runs, para: Paragraph, book: FontBook, mode: str, line_index: int = 0, spacing=(0.0, 0.0),
           text_right: float = 0.0):
    """Calcule la position de chaque caractère du nouveau texte.

    Renvoie (lignes, nombre de lignes, débordement en points vers la droite).
    """
    chars = [(ch, sk) for text, sk in runs for ch in text]
    cs, ws = spacing
    widths = _measure(chars, book, cs, ws)

    if mode == "line":
        lines = [list(range(len(chars)))] if chars else []
        orig = para.lines[line_index]
        baselines = [orig.baseline]
        is_last = [line_index == len(para.lines) - 1]
        starts_para = [line_index == 0]
    else:
        # découpage en mots et retour à la ligne automatique
        lines, cur, cur_w = [], [], 0.0
        wrap_right = para.right if para.align == "justify" else max(para.right, para.limit or para.right)
        avail_first = wrap_right - (para.left + para.indent)
        avail = wrap_right - para.left
        forced = []
        i = 0
        tokens = []  # (indices, est_espace, est_saut)
        while i < len(chars):
            if chars[i][0] == "\n":
                tokens.append(([i], False, True))
                i += 1
                continue
            j = i
            sp = chars[i][0] == " "
            while j < len(chars) and chars[j][0] != "\n" and (chars[j][0] == " ") == sp:
                j += 1
            tokens.append((list(range(i, j)), sp, False))
            i = j
        for idx, is_space, is_break in tokens:
            if is_break:
                lines.append(cur)
                forced.append(True)
                cur, cur_w = [], 0.0
                continue
            w = sum(widths[k] for k in idx)
            limit = avail_first if not lines else avail
            if not is_space and cur and cur_w + w > limit + 0.01:
                # retirer les espaces de fin
                while cur and chars[cur[-1]][0] == " ":
                    cur.pop()
                lines.append(cur)
                forced.append(False)
                cur, cur_w = [], 0.0
            if is_space and not cur:
                continue
            cur.extend(idx)
            cur_w += w
        while cur and chars[cur[-1]][0] == " ":
            cur.pop()
        if cur or not lines:
            lines.append(cur)
            forced.append(True)
        baselines = []
        for k in range(len(lines)):
            if k < len(para.lines):
                baselines.append(para.lines[k].baseline)
            else:
                baselines.append(para.lines[-1].baseline + para.pitch * (k - len(para.lines) + 1))
        is_last = [f for f in forced]
        is_last[-1] = True
        starts_para = [k == 0 or forced[k - 1] for k in range(len(lines))]

    placed_lines: list[list[Placed]] = []
    overflow = 0.0
    for k, idxs in enumerate(lines):
        y = baselines[k]
        natural = sum(widths[i] for i in idxs)
        if mode == "line":
            orig = para.lines[line_index]
            left = orig.left
            width = (para.right - left) if para.align in ("justify", "right", "center") else None
        else:
            left = para.left + (para.indent if starts_para[k] and k == 0 else 0.0)
            width = para.right - left
        x = left
        extra_per_space = 0.0
        align = para.align
        if align == "center" and width:
            if mode == "line" and len(para.lines) == 1:
                center = (para.lines[0].left + para.lines[0].right) / 2
                x = center - natural / 2
            else:
                x = left + (width - natural) / 2
        elif align == "right" and width:
            x = left + width - natural
        elif align == "justify" and width and not is_last[k] and natural < width:
            spaces = [i for i in idxs if chars[i][0] == " "]
            if spaces:
                extra_per_space = (width - natural) / len(spaces)
        row = []
        for i in idxs:
            ch, sk = chars[i]
            row.append(Placed(ch, sk, x, y, book.styles[sk].size))
            x += widths[i] + (extra_per_space if ch == " " else 0.0)
        if mode == "para" and para.align == "justify":
            limit = para.right
        else:
            limit = max(para.right, text_right)
        overflow = max(overflow, x - limit)
        placed_lines.append(row)
    return placed_lines, len(lines), overflow


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------
def _removal_rects(chars: list[Char]) -> list[pymupdf.Rect]:
    """Bandes fines à mi-hauteur des caractères : seuls eux sont supprimés."""
    rects = []
    cur = None
    for c in chars:
        y0, y1 = c.oy - c.size * 0.48, c.oy - c.size * 0.18
        if cur and abs(cur[1] - y0) < 0.01 and abs(c.x0 - cur[2]) < 0.5:
            cur[2] = c.x1
        else:
            if cur:
                rects.append(cur)
            cur = [c.x0, y0, c.x1, y1]
    if cur:
        rects.append(cur)
    out = []
    for x0, y0, x1, y1 in rects:
        inset = min(0.3, (x1 - x0) / 4)
        out.append(pymupdf.Rect(x0 + inset, y0, x1 - inset, y1))
    return out


def _common_prefix(old: list[Char], new: list[Placed]) -> int:
    k = 0
    while k < len(old) and k < len(new) and old[k].c == new[k].c and old[k].style == new[k].style:
        k += 1
    return k


def plan(page_text: PageText, edit: dict, book: FontBook):
    """Prépare une modification : caractères à supprimer, caractères à écrire, avertissements."""
    para = page_text.find(edit["key"])
    if para is None:
        raise ValueError("Zone de texte introuvable (le document a peut-être changé).")
    mode = edit.get("mode", "para")
    runs = [(t, s if s in page_text.styles else next(iter(page_text.styles))) for t, s in edit["runs"] if t]
    for t, sk in runs:
        book.need_text(sk, t)
    warnings = []
    if mode == "line":
        li = int(edit.get("line", 0))
        old_lines = [para.lines[li]]
        spacing = _spacing(para.lines[li], book)
        if para.align == "justify":
            spacing = (spacing[0], 0.0)
        new_lines, n, overflow = layout(runs, para, book, "line", li, spacing, page_text.text_right)
    else:
        old_lines = para.lines
        spacing = _spacing(max(para.lines, key=lambda l: len(l.chars)), book)
        if para.align == "justify":
            spacing = (spacing[0], 0.0)
        new_lines, n, overflow = layout(runs, para, book, "para", 0, spacing, page_text.text_right)
    remove: list[Char] = []
    draw: list[Placed] = []
    n_old, n_new = len(old_lines), len(new_lines)
    for k in range(max(n_old, n_new)):
        old = old_lines[k].chars if k < n_old else []
        new = new_lines[k] if k < n_new else []
        if old and new:
            o_vis = [(c.c, c.style) for c in old]
            n_vis = [(c.c, c.style) for c in new]
            while o_vis and o_vis[-1][0].isspace():
                o_vis.pop()
            while n_vis and n_vis[-1][0].isspace():
                n_vis.pop()
            same_text = o_vis == n_vis
            same_place = abs(old[0].oy - new[0].y) < 0.6 and (
                para.align == "justify" or abs(old[0].ox - new[0].x) < 0.6)
            same_role = mode == "line" or ((k == n_old - 1) == (k == n_new - 1))
            if same_text and same_place and same_role:
                continue  # ligne inchangée : le rendu d'origine est conservé tel quel
        keep = 0
        if old and new and para.align != "justify" and abs(old[0].ox - new[0].x) < 0.25 \
                and abs(old[0].oy - new[0].y) < 0.6:
            keep = _common_prefix(old, new)
            # le début de ligne n'est conservé que si les positions concordent exactement
            while keep > 0 and abs(old[keep - 1].ox - new[keep - 1].x) > 0.25:
                keep -= 1
        remove.extend(old[keep:])
        draw.extend(new[keep:])
    if mode == "para" and n > len(para.lines):
        warnings.append(f"le paragraphe s'allonge de {n - len(para.lines)} ligne(s) : vérifiez qu'il ne "
                        "chevauche pas le texte qui suit")
    if overflow > 1.0:
        warnings.append("le texte modifié dépasse la marge droite du document")
    return remove, draw, warnings


def _chunks(draw: list[Placed], book: FontBook):
    """Regroupe les caractères consécutifs posés à l'espacement naturel de la police."""
    chunks = []
    for p in draw:
        if p.c == "\n":
            continue
        if chunks:
            c = chunks[-1]
            last = c["chars"][-1]
            if last.style == p.style and abs(last.y - p.y) < 0.01:
                f = book.font(p.style).font
                expected = last.x + f.text_length(last.c, fontsize=book.styles[p.style].size)
                if abs(expected - p.x) < 0.02:
                    c["chars"].append(p)
                    continue
        chunks.append({"style": p.style, "chars": [p]})
    return chunks


def apply_text_edits(page: pymupdf.Page, edits: list[dict], page_text: PageText | None = None) -> list[str]:
    """Applique les modifications de texte d'une page. Renvoie les avertissements."""
    if not edits:
        return []
    page_text = page_text or analyze(page)
    book = FontBook(page_text.styles)
    for e in edits:
        for t, sk in e["runs"]:
            if sk in page_text.styles:
                book.need_text(sk, t)
    all_remove, all_draw, warnings = [], [], []
    for e in edits:
        r, d, w = plan(page_text, e, book)
        all_remove.extend(r)
        all_draw.extend(d)
        warnings.extend(w)
    # 1) suppression des caractères concernés, sans rien masquer d'autre
    if all_remove:
        for rect in _removal_rects(all_remove):
            page.add_redact_annot(rect, fill=False, cross_out=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    # 2) écriture du nouveau texte, par morceaux continus
    writers: dict[int, pymupdf.TextWriter] = {}
    for ch in _chunks(all_draw, book):
        text = "".join(p.c for p in ch["chars"])
        if not text.strip():
            continue
        st = page_text.styles[ch["style"]]
        tw = writers.get(st.color)
        if tw is None:
            tw = writers[st.color] = pymupdf.TextWriter(page.rect, color=st.rgb)
        first = ch["chars"][0]
        tw.append((first.x, first.y), text, font=book.font(ch["style"]).font, fontsize=st.size)
    for tw in writers.values():
        tw.write_text(page)
    book.collect_notes({p.style for p in all_draw})
    warnings.extend(sorted(book.notes))
    return warnings


def zone_runs(page_text: PageText, key: str, mode: str, line: int = 0):
    para = page_text.find(key)
    if para is None:
        return []
    return para.lines[line].runs() if mode == "line" else para.runs()
