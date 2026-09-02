# Vacuum Guardian — pacote portátil

Monitor de tela para CNC CMS Brembana (OSAI). Observa a tela do OSAI e, quando o
operador está prestes a iniciar um programa, verifica se o **Vacuum 1** está
ligado. Se estiver desligado — ou se não for possível verificar — dispara alarme
visual e sonoro. Ele apenas observa a tela: não modifica o OSAI nem se integra à
CNC.

## Download

Baixe o `.zip` na aba **[Releases](../../releases)** deste repositório.

## Instalação (portátil, sem instalador)

1. Extraia o `VacuumGuardian-portable.zip` numa pasta **nova e vazia**
   (ex.: `C:\VacuumGuardian`).
2. Mantenha a pasta `_internal` junto do `VacuumGuardian.exe` — ela é obrigatória.
3. Execute `VacuumGuardian.exe`. Não precisa de Python nem de direitos de
   administrador.

Ao atualizar de uma versão anterior, **não copie** o `config.json` nem a pasta
`assets\templates` da instalação antiga: recalibre do zero.

Na primeira execução o app cria, ao lado do `.exe`: `config.json`,
`assets\templates\` e `logs\`. O guia do operador acompanha o pacote como
`READ ME - Quick start.txt`.

## Como ele decide (campo Iso lines)

O gatilho é o campo **Iso lines**, no canto inferior esquerdo da tela do OSAI —
é ele que acompanha a execução do programa:

| Iso lines | O que o app faz |
|---|---|
| stand-by (código irrelevante) | silêncio |
| `CLOSE THE DOORS` e o Vacuum 1 não está ON | **alerta** — ainda dá tempo de ligar |
| o texto muda depois do aviso, com o Vacuum 1 desligado | **alerta** — a máquina já está cortando |
| o texto muda, mas o Vacuum 1 não pôde ser lido | **alerta** — nunca silêncio sem ter verificado |

Toda partida feita com o vácuo desligado gera uma linha em
`logs\overrides.csv`, com data e hora, para o gerente conferir se o aviso foi
ignorado de propósito.

O alarme é uma janela laranja, grande e pulsante, sempre em primeiro plano.
Tem **um botão**: *Acknowledge*. Ele registra a ciência do operador em
`logs\alarm_actions.csv`, libera a tela do OSAI e **silencia o alerta por 5
minutos** — tempo de ir até a máquina sem o aviso voltando a cada segundo. O
monitoramento não para nesse período, e religar o vácuo encerra o silêncio na
hora. O som é opcional (fábrica barulhenta, PC sem alto-falante) e pode ser
desligado nas Configurações — o aviso visual não depende dele.

## Compatibilidade com o Windows

Windows 10 e 11 (x64). O pacote é **autossuficiente**.

A interface usa **Qt 5 (PySide2)**, e não Qt 6: o controlador desta CNC roda
Windows 10 Enterprise 2016 LTSB (build 1607), e todo release do Qt 6 exige
Windows 10 1809 ou superior — nele o PySide6 falha com *"DLL load failed while
importing QtCore"*. O PySide2 é compilado sem ICU, então o pacote também não
depende das bibliotecas Unicode do sistema.

## Calibração (antes do primeiro uso)

Feita na máquina, com o OSAI aberto. O app traz um **assistente passo a passo**
(alterna entre português e inglês) que conduz a sequência inteira; o
`READ ME - Quick start.txt` do pacote tem o mesmo roteiro.

1. **Settings** → informe um trecho do título da janela do OSAI.
2. **Calibrate ROIs / Templates** → o assistente pede, para cada indicador
   (`Vacuum Pump 1` e depois `Vacuum 1`): o nome, o botão ON/OFF e uma amostra
   de como é LIGADO e DESLIGADO.
3. **Capturar a área do campo Iso lines** — passo obrigatório: é o gatilho do
   alerta. Sem ele o app não dispara nada.
4. Confira no painel: a linha **Machine state** deve alternar entre `stand-by`,
   `CLOSE THE DOORS - check vacuum` e `RUNNING - vacuum required` conforme a
   máquina.

Depois de calibrar, guarde uma cópia do `config.json` e da pasta
`assets\templates` — com esses dois a calibração é restaurada em segundos.

## Arquivos gerados (ao lado do `.exe`)

| Arquivo | Conteúdo |
|---|---|
| `config.json` | a calibração (regiões, limiares, indicadores) |
| `assets\templates\` | imagens aprendidas de cada indicador |
| `logs\vacuum_guardian_AAAA-MM-DD.log` | log técnico do dia (mantém 30 dias) |
| `logs\detections.csv` | auditoria: cada mudança de estado e cada alarme |
| `logs\overrides.csv` | lista curta: programas iniciados com o vácuo desligado |

---
Criado por **Marcos Souza & Andrea Cursino** — Abilix Digital ·
<https://www.abilixdigital.com>
