"""Reconnaissance des polices : retrouve, pour une police citée dans un PDF,
le fichier de police à utiliser pour écrire du texte nouveau.

Ordre de préférence :
1. la même police installée sur l'ordinateur (nom PostScript ou nom complet
   identique) — rendu identique ;
2. la police intégrée au PDF, si elle contient tous les caractères à écrire ;
3. une police de la même famille installée, avec le style le plus proche ;
4. à défaut, une police de remplacement proche (sans, avec empattements ou
   à chasse fixe) — le rendu peut alors différer légèrement.
"""
from __future__ import annotations

import os
import re
import struct
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

FONT_EXT = {".ttf", ".otf", ".ttc", ".otc"}


# --------------------------------------------------------------------------
# Lecture des noms dans les fichiers de police (table « name »)
# --------------------------------------------------------------------------
def _parse_name_table(data: bytes) -> dict[int, str]:
    try:
        fmt, count, str_off = struct.unpack_from(">HHH", data, 0)
        names: dict[int, tuple[int, str]] = {}
        for i in range(count):
            pid, eid, lid, nid, length, off = struct.unpack_from(">HHHHHH", data, 6 + 12 * i)
            if nid not in (1, 2, 4, 6, 16, 17):
                continue
            raw = data[str_off + off: str_off + off + length]
            if pid in (0, 3):
                try:
                    txt = raw.decode("utf-16-be")
                except UnicodeDecodeError:
                    continue
                score = 3 if (pid == 3 and lid == 0x409) else 2
            elif pid == 1:
                txt = raw.decode("mac_roman", errors="ignore")
                score = 1
            else:
                continue
            if nid not in names or score > names[nid][0]:
                names[nid] = (score, txt.strip("\x00 "))
        return {k: v[1] for k, v in names.items()}
    except Exception:
        return {}


def _names_at(f, offset: int) -> dict[int, str]:
    f.seek(offset)
    head = f.read(12)
    if len(head) < 12:
        return {}
    num_tables = struct.unpack_from(">H", head, 4)[0]
    recs = f.read(16 * num_tables)
    for i in range(num_tables):
        tag = recs[16 * i:16 * i + 4]
        if tag == b"name":
            off, length = struct.unpack_from(">II", recs, 16 * i + 8)
            f.seek(off)
            return _parse_name_table(f.read(min(length, 1_000_000)))
    return {}


def read_font_names(path: str) -> list[tuple[int, dict[int, str]]]:
    """Renvoie [(indice, noms)] pour chaque police du fichier (plusieurs pour un .ttc)."""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if head[:4] == b"ttcf":
                n = struct.unpack_from(">I", head, 8)[0]
                offs = struct.unpack(">" + "I" * n, f.read(4 * n))
                return [(i, _names_at(f, o)) for i, o in enumerate(offs)]
            return [(0, _names_at(f, 0))]
    except (OSError, struct.error):
        return []


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def strip_subset(name: str) -> str:
    return re.sub(r"^[A-Z]{6}\+", "", name or "")


STYLE_WORDS = ("bold", "italic", "oblique", "semibold", "demibold", "light", "medium", "black", "heavy",
               "regular", "roman", "book", "normal", "condensed", "narrow", "extrabold", "thin")


@dataclass
class FontEntry:
    path: str
    index: int
    family: str
    subfamily: str
    full: str
    ps: str

    @property
    def bold(self) -> bool:
        s = self.subfamily.lower() + " " + self.full.lower()
        return any(w in s for w in ("bold", "black", "heavy", "semibold", "demi"))

    @property
    def italic(self) -> bool:
        s = self.subfamily.lower() + " " + self.full.lower()
        return "italic" in s or "oblique" in s


def font_dirs() -> list[Path]:
    dirs = []
    if sys.platform.startswith("win"):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(Path(windir) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
                 Path.home() / ".local" / "share" / "fonts"]
    return [d for d in dirs if d.exists()]


class FontIndex:
    def __init__(self):
        self.entries: list[FontEntry] = []
        self.by_key: dict[str, FontEntry] = {}
        self.by_family: dict[str, list[FontEntry]] = {}
        self._built = False
        self._lock = threading.Lock()

    def build(self):
        with self._lock:
            if self._built:
                return
            for d in font_dirs():
                for root, _, files in os.walk(d):
                    for fn in files:
                        if Path(fn).suffix.lower() not in FONT_EXT:
                            continue
                        path = os.path.join(root, fn)
                        for idx, names in read_font_names(path):
                            if idx > 0:
                                continue  # seule la première police d'un .ttc est utilisable
                            fam = names.get(16) or names.get(1) or ""
                            sub = names.get(17) or names.get(2) or ""
                            e = FontEntry(path, idx, fam, sub, names.get(4) or f"{fam} {sub}", names.get(6) or "")
                            if not fam:
                                continue
                            self.entries.append(e)
                            for key in (e.ps, e.full, f"{fam} {sub}", f"{names.get(1, '')} {names.get(2, '')}"):
                                k = norm(key)
                                if k and k not in self.by_key:
                                    self.by_key[k] = e
                            for famname in {fam, names.get(1, "")}:
                                if famname:
                                    self.by_family.setdefault(norm(famname), []).append(e)
            self._built = True


INDEX = FontIndex()

# Polices PDF standard et équivalents courants
ALIASES = {
    "helvetica": "arial", "helveticaneue": "arial", "arialmt": "arial", "timesroman": "timesnewroman",
    "times": "timesnewroman", "timesnewromanps": "timesnewroman", "courier": "couriernew",
    "couriernewps": "couriernew", "arialnarrow": "arialnarrow", "symbolmt": "symbol",
    "liberationsans": "arial", "liberationserif": "timesnewroman", "liberationmono": "couriernew",
}
# Si l'équivalent n'existe pas (ex. tests sous Linux), familles de secours
SUBSTITUTES = {
    "arial": ["arial", "liberationsans", "helvetica", "dejavusans"],
    "timesnewroman": ["timesnewroman", "liberationserif", "dejavuserif"],
    "couriernew": ["couriernew", "liberationmono", "dejavusansmono"],
}


def _split_name(name: str):
    """« Arial-BoldItalicMT » → ('arial', bold=True, italic=True)."""
    base = strip_subset(name)
    family = re.split(r"[-,]", base)[0]
    rest = base[len(family):]
    family = re.sub(r"(PSMT|PS|MT)$", "", family)
    # nom complet de type « Liberation Sans Bold Italic »
    words = re.findall(r"[A-Za-z]+", base)
    low = base.lower()
    bold = any(w in low for w in ("bold", "black", "heavy", "semibold", "demi"))
    italic = "italic" in low or "oblique" in low or low.endswith(",it")
    if " " in base:
        fam_words = [w for w in words if w.lower() not in STYLE_WORDS and w.lower() not in ("mt", "ps")]
        family = " ".join(fam_words)
    return norm(family), bold, italic


@dataclass
class ResolvedFont:
    font: pymupdf.Font
    label: str            # nom lisible de la police utilisée
    exact: bool           # True si c'est la police d'origine
    path: str | None = None
    index: int = 0
    buffer: bytes | None = None
    note: str = ""


_FONT_CACHE: dict = {}


def _load(path, index=0, buffer=None) -> pymupdf.Font:
    key = (path, index, None if buffer is None else hash(buffer))
    f = _FONT_CACHE.get(key)
    if f is None:
        f = pymupdf.Font(fontbuffer=buffer) if buffer is not None else pymupdf.Font(fontfile=path)
        _FONT_CACHE[key] = f
    return f


def _covers(font: pymupdf.Font, text: str) -> bool:
    for ch in set(text):
        if ch in "\n\r\t":
            continue
        if not font.has_glyph(ord(ch)):
            return False
    return True


def _pick_style(cands: list[FontEntry], bold: bool, italic: bool) -> FontEntry | None:
    if not cands:
        return None

    def score(e: FontEntry):
        s = 0
        s += 0 if e.bold == bold else 2
        s += 0 if e.italic == italic else 2
        sub = e.subfamily.lower()
        if not bold and not italic and sub in ("regular", "normal", "book", "roman"):
            s -= 1
        if "condensed" in sub or "narrow" in sub:
            s += 1
        return s

    return sorted(cands, key=score)[0]


def resolve(pdf_font_name: str, flags: int = 0, text: str = "", embedded: bytes | None = None) -> ResolvedFont:
    """Trouve la police à utiliser pour écrire `text` à la place d'un texte en `pdf_font_name`."""
    INDEX.build()
    base = strip_subset(pdf_font_name)
    bold_flag = bool(flags & 16)
    italic_flag = bool(flags & 2)
    fam, bold_n, italic_n = _split_name(base)
    bold = bold_n or bold_flag
    italic = italic_n or italic_flag

    # 1) même police installée
    for key in (norm(base), norm(re.sub(r"(PSMT|MT)$", "", base))):
        e = INDEX.by_key.get(key)
        if e and e.bold == bold and e.italic == italic or (e and key == norm(base)):
            f = _load(e.path, e.index)
            if _covers(f, text):
                return ResolvedFont(f, e.full, True, e.path, e.index)

    # 2) police intégrée au document, si elle contient tous les caractères
    if embedded:
        try:
            f = _load(None, 0, embedded)
            if f.glyph_count > 0 and _covers(f, text or "a"):
                return ResolvedFont(f, base, True, buffer=embedded)
        except Exception:
            pass

    # 3) même famille installée
    fam_key = ALIASES.get(fam, fam)
    exact_family = fam_key == fam or fam in ("helvetica", "times", "timesroman", "courier", "arialmt")
    for cand in [fam_key] + SUBSTITUTES.get(fam_key, []):
        e = _pick_style(INDEX.by_family.get(cand, []), bold, italic)
        if e:
            f = _load(e.path, e.index)
            if _covers(f, text):
                same = exact_family and cand == fam_key and e.bold == bold and e.italic == italic
                note = "" if same else f"police « {base} » non installée : remplacée par « {e.full} »"
                return ResolvedFont(f, e.full, same, e.path, e.index, note=note)

    # 4) police de remplacement selon le genre
    serif = bool(flags & 4) or any(w in fam for w in ("times", "roman", "serif", "garamond", "georgia",
                                                      "cambria", "book", "minion", "palatino"))
    mono = bool(flags & 8) or any(w in fam for w in ("courier", "mono", "consolas"))
    genre = "couriernew" if mono else ("timesnewroman" if serif else "arial")
    for cand in SUBSTITUTES[genre]:
        e = _pick_style(INDEX.by_family.get(cand, []), bold, italic)
        if e:
            f = _load(e.path, e.index)
            if _covers(f, text):
                return ResolvedFont(f, e.full, False, e.path, e.index,
                                    note=f"police « {base} » non installée : remplacée par « {e.full} »")
    code = {("couriernew", False, False): "cour", ("couriernew", True, False): "cobo",
            ("couriernew", False, True): "coit", ("couriernew", True, True): "cobi",
            ("timesnewroman", False, False): "tiro", ("timesnewroman", True, False): "tibo",
            ("timesnewroman", False, True): "tiit", ("timesnewroman", True, True): "tibi",
            ("arial", False, False): "helv", ("arial", True, False): "hebo",
            ("arial", False, True): "heit", ("arial", True, True): "hebi"}[(genre, bold, italic)]
    return ResolvedFont(pymupdf.Font(code), code, False,
                        note=f"police « {base} » non installée : remplacée par une police standard")
