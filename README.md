# Vacuum Guardian — pacote portátil

Monitor de tela para CNC CMS Brembana (OSAI). Observa a tela do OSAI e, enquanto
um programa monitorado está rodando, verifica se os indicadores **Vacuum Pump** e
**Vacuum1** estão ON. Se algum estiver OFF, dispara alarme visual e sonoro. Ele
apenas observa a tela — não modifica nem integra com a CNC.

## Download

Baixe o `.zip` na aba **[Releases](../../releases)** deste repositório.

## Instalação (portátil, sem instalador)

1. Extraia o `VacuumGuardian-portable.zip` em qualquer pasta (ex.: `C:\VacuumGuardian`).
2. Mantenha a pasta `_internal` junto do `VacuumGuardian.exe` — ela é obrigatória.
3. Execute `VacuumGuardian.exe`. Não precisa de Python nem de direitos de administrador.

Na primeira execução o app cria, ao lado do `.exe`: `config.json`,
`assets\templates\` e `logs\`. O guia do operador acompanha o pacote como
`READ ME - Quick start.txt`.

## Compatibilidade com o Windows

Este pacote é **autossuficiente** e roda em Windows 10 e 11 (x64).

As bibliotecas ICU do Windows (`icuuc.dll`, `icuin.dll`, `icu.dll`), das quais o
Qt6 depende, vêm **empacotadas** dentro de `_internal\PySide6\`. Isso corrige o
erro *"DLL load failed while importing QtCore: The specified module could not be
found"* que ocorria em versões mais antigas do Windows 10 (LTSC / builds
anteriores à 1903), onde essas DLLs não existem no sistema.

## Calibração (antes do primeiro uso)

Necessária na máquina, com o OSAI aberto — ver `READ ME - Quick start.txt`
incluído no pacote. Resumo: Settings → definir o título da janela do OSAI →
Calibrate ROIs / Templates → marcar as regiões e capturar os templates ON/OFF de
cada indicador.

---
Criado por **Marcos Souza & Andrea Cursino** — Abilix Digital ·
<https://www.abilixdigital.com>
