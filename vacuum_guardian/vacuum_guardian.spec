# -*- mode: python ; coding: utf-8 -*-
"""Especificacao do PyInstaller (requisito 11).

Decisoes:
- onedir (nao onefile): inicia bem mais rapido e evita que o antivirus
  inspecione um executavel auto-extraivel a cada boot - relevante para um
  app que sobe junto com o Windows;
- console=False: roda em segundo plano, sem janela de terminal;
- assets embarcados (icone, som, templates); config.json e logs ficam ao
  lado do .exe, gravaveis (ver app/utils/paths.py);
- exclusao de modulos pesados nao usados (torch, matplotlib, tkinter) para
  reduzir o tamanho do pacote.

Uso:  pyinstaller vacuum_guardian.spec --noconfirm
"""

# Qt5 (PySide2) e usado no lugar do Qt6 porque o alvo e um Windows 10 build
# 1607 (LTSB 2016), anterior ao minimo do Qt6 (Windows 10 1809). O PySide2 e
# compilado SEM ICU, entao nao ha DLLs de ICU para empacotar: o Qt5 traz seus
# proprios codecs Unicode e nao depende da ICU do sistema.
a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("assets/icon.svg", "assets"),
        ("assets/icon.ico", "assets"),
        ("assets/alarm.wav", "assets"),
        ("assets/templates", "assets/templates"),
    ],
    hiddenimports=[
        # Modulos winrt sao carregados dinamicamente pelo OCR nativo.
        "winrt.windows.media.ocr",
        "winrt.windows.globalization",
        "winrt.windows.graphics.imaging",
        "winrt.windows.security.cryptography",
        "winrt.windows.storage.streams",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Nunca usados: manter fora reduz o pacote e a superficie de ataque.
        # ATENCAO: nao excluir QtQml nem QtNetwork - o pyside2.abi3.dll (nucleo
        # do PySide2 5.15) tem dependencia *hard* de Qt5Qml.dll, que por sua vez
        # depende de Qt5Network.dll. Remove-las quebra o import de QtCore.
        "torch", "matplotlib", "tkinter", "scipy", "pandas", "PIL",
        "PySide2.QtWebEngine", "PySide2.QtWebEngineWidgets",
        "PySide2.QtWebEngineCore", "PySide2.Qt3DCore", "PySide2.QtCharts",
        "PySide2.QtMultimedia",
    ],
    noarchive=False,
)

# Poda binarios que o Qt arrasta mas este app nao usa. Conservador de proposito:
# opengl32sw.dll sozinho pesa ~20 MB (renderizador OpenGL por software,
# desnecessario para widgets). NAO podar DLLs Qt5* aqui: o pyside2.abi3.dll
# encadeia Qt5Qml -> Qt5Network, e podar qualquer uma quebra o carregamento.
_UNUSED_BINARIES = (
    "opengl32sw.dll",
)
a.binaries = TOC(
    entry for entry in a.binaries
    if not any(token.lower() in entry[0].lower() for token in _UNUSED_BINARIES)
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VacuumGuardian",
    debug=False,
    strip=False,
    upx=False,          # UPX costuma disparar falso positivo de antivirus
    console=False,      # sem janela de terminal (roda em segundo plano)
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VacuumGuardian",
)
