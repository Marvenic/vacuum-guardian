"""Camada grafica (PySide2 / Qt 5.15). Apenas apresentacao - zero regra de negocio.

Qt5 (e nao Qt6) porque o alvo e um controlador de CNC com Windows 10 build 1607
(LTSB 2016), anterior ao minimo do Qt6 (Windows 10 1809). O Qt 5.15 suporta
Windows 7/8/10 e o PySide2 e compilado sem ICU (nao depende da ICU do sistema).
"""
