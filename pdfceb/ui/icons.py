"""Icônes vectorielles (SVG 24×24, trait) dessinées pour PDF Ceb."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    # --- outils
    "merge": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="9" rx="1.5"/>'
             '<path d="M6.5 12v2.5a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2V12"/><path d="M12 16.5V21"/><path d="M9.5 18.8 12 21l2.5-2.2"/>',
    "split": '<rect x="3" y="4" width="7" height="16" rx="1.5"/><rect x="14" y="4" width="7" height="16" rx="1.5"/>'
             '<path d="M12 2v2M12 7v2M12 12v2M12 17v2M12 22v0"/>',
    "delete": '<path d="M4 7h16"/><path d="M9.5 7V4.5h5V7"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v5.5M14 11v5.5"/>',
    "extract": '<path d="M13 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21H13"/><path d="M9 8h4M9 12h3"/>'
               '<path d="M11 15.5h10M17.5 12l3.5 3.5-3.5 3.5"/>',
    "organize": '<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/>'
                '<rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>',
    "compress": '<path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="M14 10l7-7"/><path d="M3 21l7-7"/>',
    "repair": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z"/>',
    "img2pdf": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M21 15.5l-5-5L6 20"/>',
    "pdf2img": '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5"/>'
               '<circle cx="9.5" cy="12" r="1.3"/><path d="M19 17l-3.5-3.5L9 20"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "rotate": '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1L20.5 8"/><path d="M20.5 3v5h-5"/>',
    "rotate_left": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8"/><path d="M3.5 3v5h5"/>',
    "numbers": '<path d="M5 9h15M4 15h15M10.5 3.5 8.5 20.5M15.5 3.5l-2 17"/>',
    "watermark": '<path d="M12 3s6.5 6.6 6.5 11.2a6.5 6.5 0 0 1-13 0C5.5 9.6 12 3 12 3z"/><path d="M9 15a3 3 0 0 0 3 3"/>',
    "crop": '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    "form": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h5M7 14.5h5"/><rect x="14.5" y="7.5" width="3" height="3" rx=".5"/>'
            '<path d="M14.5 14.5h3"/>',
    "protect": '<rect x="4.5" y="10.5" width="15" height="10.5" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/><path d="M12 14.5v3"/>',
    "unlock": '<rect x="4.5" y="10.5" width="15" height="10.5" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 7.6-1.8"/><path d="M12 14.5v3"/>',
    "sign": '<path d="M3 16.5c2.5-.5 3.6-8.5 5.8-8.5 1.9 0-.9 8.5 1.2 8.5 1.7 0 2.6-4.6 4.6-4.6 1.6 0 .9 3.9 2.6 3.9 1 0 2-.8 2.8-1.8"/>'
            '<path d="M3 20.5h18"/>',
    "redact": '<path d="M4 6h16M4 18h16M4 12h5"/><rect x="11" y="9.5" width="9" height="5" rx="1" fill="currentColor"/>',
    "compare": '<rect x="3" y="4" width="7.5" height="16" rx="1.5"/><rect x="13.5" y="4" width="7.5" height="16" rx="1.5"/>'
               '<path d="M5.5 8.5h2.5M5.5 12h2.5M16 8.5h2.5M16 15.5h2.5"/>',
    "extractimg": '<rect x="7" y="3" width="14" height="12" rx="1.5"/><circle cx="11.5" cy="7.5" r="1.3"/><path d="M21 12l-3.5-3.5L12 14"/>'
                  '<path d="M4 7v12a2 2 0 0 0 2 2h12"/>',
    # --- interface
    "home": '<path d="M3.5 11 12 3.5l8.5 7.5"/><path d="M5.5 9.5V20h4.5v-6h4v6h4.5V9.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "file": '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "upload": '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19.5 7"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "sort": '<path d="M7 4v16M3.5 16.5 7 20l3.5-3.5"/><path d="M13 6h8M13 11h6M13 16h4"/>',
    "blank": '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5"/>'
             '<path d="M12 11.5v6M9 14.5h6"/>',
    "reverse": '<path d="M7 20V4M3.5 7.5 7 4l3.5 3.5"/><path d="M17 4v16M13.5 16.5 17 20l3.5-3.5"/>',
    "select": '<path d="M5.5 3.5 18 11l-5.6 1.6L9.5 18.5z"/><path d="M12.4 12.6 17 17.2"/>',
    "text": '<path d="M5 7V4.5h14V7"/><path d="M12 4.5v15"/><path d="M9 19.5h6"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M21 15.5l-5-5L6 20"/>',
    "rect": '<rect x="4" y="6" width="16" height="12" rx="1"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="9" ry="6.5"/>',
    "line": '<path d="M5 19 19 5"/>',
    "arrow": '<path d="M5 19 19 5"/><path d="M10 5h9v9"/>',
    "ink": '<path d="M3 17.5c2.5-6 4.5-8 6-6.5s-1.5 6 .8 6.5c2.4.5 3.7-7.8 6.5-7.3 1.7.3 1.2 3.6 4.7 3.3"/>',
    "highlight": '<path d="m9 11-5.5 5.5V20h3.5l5.5-5.5"/><path d="m9 11 4.5-7 7 7-7 4.5z"/><path d="M14 20h7"/>',
    "whiteout": '<path d="M7.5 20.5h12"/><path d="M5 15.5 14.5 6l5 5-8.5 8.5H8.5z"/><path d="M10 10.5l5 5"/>',
    "note": '<path d="M4 5h16v11H10l-6 4.5z"/><path d="M8 9h8M8 12.5h5"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    "zoom_in": '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.5-4.5M8 11h6M11 8v6"/>',
    "zoom_out": '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.5-4.5M8 11h6"/>',
    "fit": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "save": '<path d="M5 3.5h11l4 4V19a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3.5 19V5A1.5 1.5 0 0 1 5 3.5z"/>'
            '<path d="M8 3.5v4.5h7V3.5M7.5 20.5v-6h9v6"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.5-4.5"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "shield": '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.9 7.5-9.5V6z"/><path d="m9 12 2 2 4-4"/>',
    "trash": '<path d="M4 7h16"/><path d="M9.5 7V4.5h5V7"/><path d="M6 7l1 13h10l1-13"/>',
    "color": '<circle cx="12" cy="12" r="8.5"/>',
    "chev_up": '<path d="M6 15l6-6 6 6"/>',
    "chev_down": '<path d="M6 9l6 6 6-6"/>',
}


def svg(name: str, color: str = "#1f2430", width: float = 1.8, fill: str = "none") -> str:
    body = _P.get(name, _P["file"]).replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


@lru_cache(maxsize=512)
def pixmap(name: str, color: str = "#1f2430", size: int = 24, dpr: float = 2.0, width: float = 1.8) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg(name, color, width).encode("utf-8")))
    img = QImage(int(size * dpr), int(size * dpr), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = "#1f2430", size: int = 24) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size))
    ic.addPixmap(pixmap(name, "#ffffff", size), QIcon.Mode.Selected)
    ic.addPixmap(pixmap(name, "#a0a6b4", size), QIcon.Mode.Disabled)
    return ic


APP_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#4c6ef5"/><stop offset="1" stop-color="#3b3fc4"/></linearGradient></defs>'
    '<rect x="2" y="2" width="60" height="60" rx="14" fill="url(#g)"/>'
    '<path d="M21 13h16l10 10v26a3 3 0 0 1-3 3H21a3 3 0 0 1-3-3V16a3 3 0 0 1 3-3z" fill="#ffffff"/>'
    '<path d="M37 13v8a2 2 0 0 0 2 2h8z" fill="#c5cdfb"/>'
    '<path d="M24 33h16M24 39h16M24 45h10" stroke="#4c6ef5" stroke-width="3" stroke-linecap="round"/>'
    '</svg>'
)


def app_icon() -> QIcon:
    renderer = QSvgRenderer(QByteArray(APP_SVG.encode("utf-8")))
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        img = QImage(s, s, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p, QRectF(0, 0, s, s))
        p.end()
        ic.addPixmap(QPixmap.fromImage(img))
    return ic


def app_pixmap(size: int = 32) -> QPixmap:
    return app_icon().pixmap(QSize(size, size))
