"""Ponto de entrada do Vacuum Guardian.

Composicao (composition root): carrega config, monta o MonitorEngine e a
janela principal, e entrega o controle ao loop do Qt. Toda a fiacao de
dependencias acontece aqui - nenhum modulo interno importa outro "por fora".
"""

from __future__ import annotations

import faulthandler
import sys
from pathlib import Path

from loguru import logger

from app import __version__


def _enable_crash_dump(log_dir: Path) -> None:
    """Grava a pilha nativa em logs/crash.log se o processo morrer de vez.

    Um crash em C (OpenCV, Qt, driver de video) mata o processo sem passar pelo
    Python: o operador so ve "VacuumGuardian.exe has stopped working" e nao
    sobra nada no log. Com o faulthandler ligado, fica um arquivo dizendo em
    qual chamada o processo caiu - a diferenca entre diagnosticar e adivinhar.

    O arquivo fica ABERTO durante toda a execucao de proposito: no momento do
    crash nao ha como abri-lo.
    """
    try:
        handle = (log_dir / "crash.log").open("a", encoding="utf-8")
        faulthandler.enable(file=handle, all_threads=True)
    except OSError as exc:  # sem permissao de escrita: seguir sem o dump
        logger.warning("Could not enable the crash dump: {}", exc)


def main() -> int:
    from app.config import ConfigService
    from app.logging import setup_logging
    from app.services.monitor import MonitorEngine
    from app.ui.main_window import MainWindow
    from app.utils import user_data_path
    from PySide2.QtCore import Qt
    from PySide2.QtWidgets import QApplication

    # Config e logs sao gravaveis: ficam ao lado do .exe (ou na raiz em dev),
    # nunca na pasta temporaria que o PyInstaller descarta ao fechar.
    PROJECT_ROOT = user_data_path()
    (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
    setup_logging(PROJECT_ROOT / "logs")
    _enable_crash_dump(PROJECT_ROOT / "logs")
    logger.info("Vacuum Guardian starting v{}", __version__)

    config_service = ConfigService(PROJECT_ROOT / "config.json")
    config = config_service.load()

    # High-DPI: no Qt6 e automatico; no Qt5 precisa ser ligado explicitamente
    # ANTES de criar o QApplication. Mantem as fontes em pontos (unidade fisica)
    # com o mesmo tamanho real em Full HD e 4K, como documentado no alarme.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # fechar janela nao encerra (fica na bandeja)

    engine = MonitorEngine(config, PROJECT_ROOT)
    window = MainWindow(engine, config_service, PROJECT_ROOT)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
