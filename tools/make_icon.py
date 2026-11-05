"""Génère assets/icon.ico à partir de l'icône vectorielle de l'application."""
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

from pdfceb.ui.icons import APP_SVG  # noqa: E402

app = QGuiApplication(sys.argv)
renderer = QSvgRenderer(QByteArray(APP_SVG.encode("utf-8")))
img = QImage(256, 256, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
renderer.render(p, QRectF(0, 0, 256, 256))
p.end()
ba = QByteArray()
buf = QBuffer(ba)
buf.open(QIODevice.WriteOnly)
img.save(buf, "PNG")
buf.close()
pil = Image.open(io.BytesIO(bytes(ba))).convert("RGBA")
out = Path(__file__).resolve().parents[1] / "assets"
out.mkdir(exist_ok=True)
pil.save(out / "icon.png")
pil.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icône créée :", out / "icon.ico")
