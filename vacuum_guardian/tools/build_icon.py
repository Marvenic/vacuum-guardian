"""Gera assets/icon.ico (multi-resolucao) a partir de assets/icon.svg.

Usa apenas Qt (ja e dependencia do app) + struct da stdlib: renderiza o SVG
em varias resolucoes e monta o container ICO com entradas PNG (suportado
pelo Windows desde o Vista). Evita adicionar Pillow so para isso.

Uso:  python tools/build_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide2.QtCore import QBuffer, QByteArray, Qt
from PySide2.QtGui import QImage, QPainter
from PySide2.QtSvg import QSvgRenderer
from PySide2.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "icon.svg"
ICO = ROOT / "assets" / "icon.ico"
ACCENT_OK = "#3ddc97"  # verde-agua: legivel em fundo claro e escuro
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_png(svg_source: str, size: int) -> bytes:
    """Renderiza o SVG em `size`x`size` e devolve os bytes PNG."""
    renderer = QSvgRenderer(QByteArray(svg_source.encode("utf-8")))
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()

    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def build_ico(pngs: dict[int, bytes], destination: Path) -> None:
    """Monta o container ICO (ICONDIR + ICONDIRENTRY por tamanho)."""
    count = len(pngs)
    header = struct.pack("<HHH", 0, 1, count)  # reservado, tipo 1 = icone, qtd
    offset = 6 + 16 * count                    # dados comecam apos os headers
    entries, blobs = b"", b""
    for size, data in sorted(pngs.items()):
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,  # 0 significa 256 no formato ICO
            0 if size >= 256 else size,
            0,      # paleta
            0,      # reservado
            1,      # planos
            32,     # bits por pixel
            len(data),
            offset,
        )
        blobs += data
        offset += len(data)
    destination.write_bytes(header + entries + blobs)


def main() -> int:
    QApplication(sys.argv)  # necessario para o pipeline de imagem do Qt
    svg_source = SVG.read_text(encoding="utf-8").replace("{ACCENT}", ACCENT_OK)
    pngs = {size: render_png(svg_source, size) for size in SIZES}
    build_ico(pngs, ICO)
    (ROOT / "assets" / "icon.png").write_bytes(pngs[256])  # preview/documentacao
    print(f"{ICO} gerado ({ICO.stat().st_size} bytes, tamanhos: {sorted(pngs)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
