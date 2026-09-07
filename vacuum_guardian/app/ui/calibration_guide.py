"""Calibration wizard embedded in the UI, in English and Portuguese.

Why it exists: the old screen showed all seven calibration buttons at once,
in two rows of different modes, and the operator had no way to know the
order. Here there is ONE step at a time with ONE action button - the order
stops being tribal knowledge and becomes the interface itself.

This module DRIVES the wizard: it owns the script, knows which step is
current and which action it triggers. The one that EXECUTES the action
(cropping, writing the PNG) is the calibration window, via a handler.

The progress list at the bottom reads the real configuration and template
files; on opening, the wizard jumps to the first step still missing.

Language: this is the only text in the app that also exists in Portuguese,
at the shop floor's request. The OSAI TARGET NAMES stay in English even in
the Portuguese version, because that is what the machine screen shows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide2.QtCore import Qt, Signal
from PySide2.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models import AppConfig

# Progress/action keys: they tie a wizard step to the artefact it produces
# and to the handler the calibration window registers.
REQ_LABEL = "label"
REQ_TOGGLE = "toggle"
REQ_ON = "on"
REQ_OFF = "off"
REQ_ISO = "iso"
ACT_PROGRAM = "program"

LANGUAGES = ("en", "pt")


def slug_of(name: str) -> str:
    """Same slug as IndicatorConfig, without needing the config object."""
    return name.strip().lower().replace(" ", "_")


def progress_key(indicator: str, requirement: str) -> str:
    """Per-indicator progress key (e.g. 'vacuum_pump_1:label').

    Progress is per indicator: calibrating one must not mark the other as
    done.
    """
    return f"{slug_of(indicator)}:{requirement}"


@dataclass(frozen=True)
class GuideStep:
    title: str
    body: str                      # simple rich text (<b>, <ul>, <br>)
    note: str = ""                 # "why this matters" - neutral background
    warning: str = ""              # known pitfall - highlighted background
    requires: str | None = None    # pending while the artefact is missing
    action: str = ""               # handler key; empty = read-only step
    needs_selection: bool = False  # requires a rectangle dragged on the image
    anchor: str = ""               # stable identity across languages
    # WHICH indicator this step belongs to (empty on general steps). Without
    # it the wizard captured everything into the critical indicator, even
    # while the text talked about another one - the source of "I calibrated
    # Vacuum Pump 1 and it still cannot be read".
    indicator: str = ""


def _capture_steps_en(name: str) -> list[GuideStep]:
    """The four capture steps for ONE indicator, in English.

    Generated PER INDICATOR (not written once for the critical one): the text
    has to name whichever indicator is being calibrated at that moment, or the
    operator captures Vacuum Pump 1 while reading instructions for Vacuum 1 -
    and the file ends up stored against the wrong indicator.
    """
    slug = slug_of(name)
    return [
        GuideStep(
            anchor="target@" + slug,
            title=name + ": pick the indicator",
            body=(
                "On the left, in <b>Target:</b>, choose <b>" + name + "</b>, then "
                "click <b>Next</b>."
            ),
            note=(
                "Scroll the OSAI menu until <b>" + name + "</b> is on screen "
                "before continuing."
            ),
            indicator=name,
        ),
        GuideStep(
            anchor="label@" + slug,
            title=name + ": capture the name",
            body=(
                "<ul>"
                "<li>On the picture, drag a tight box around "
                "<b>only the text &quot;" + name + "&quot;</b>.</li>"
                "<li>Do not include the star or the ON/OFF button.</li>"
                "<li>Click the green button below.</li>"
                "</ul>"
            ),
            note=(
                "This is how the app finds the indicator again after the menu is "
                "scrolled up or down."
            ),
            requires=progress_key(name, REQ_LABEL),
            action=REQ_LABEL,
            needs_selection=True,
            indicator=name,
        ),
        GuideStep(
            anchor="toggle@" + slug,
            title=name + ": capture the ON/OFF button",
            body=(
                "<ul>"
                "<li>Drag a box around the <b>ON/OFF button on the same row as "
                + name + "</b>.</li>"
                "<li>Click the green button below.</li>"
                "</ul>"
            ),
            requires=progress_key(name, REQ_TOGGLE),
            action=REQ_TOGGLE,
            needs_selection=True,
            indicator=name,
        ),
        GuideStep(
            anchor="on@" + slug,
            title=name + ": capture what ON looks like",
            body=(
                "<ul>"
                "<li>On the OSAI screen, switch <b>" + name + " ON</b>.</li>"
                "<li>Click the green button below. Nothing to drag this time.</li>"
                "</ul>"
            ),
            note=(
                "This window hides itself, takes a fresh picture and finds the "
                "indicator on its own."
            ),
            requires=progress_key(name, REQ_ON),
            action=REQ_ON,
            indicator=name,
        ),
        GuideStep(
            anchor="off@" + slug,
            title=name + ": capture what OFF looks like",
            body=(
                "<ul>"
                "<li>On the OSAI screen, switch <b>" + name + " OFF</b>.</li>"
                "<li>Click the green button below.</li>"
                "</ul>"
            ),
            requires=progress_key(name, REQ_OFF),
            action=REQ_OFF,
            indicator=name,
        ),
    ]


def _capture_steps_pt(name: str) -> list[GuideStep]:
    """The four capture steps for ONE indicator, in Portuguese."""
    slug = slug_of(name)
    return [
        GuideStep(
            anchor="target@" + slug,
            title=name + ": escolher o indicador",
            body=(
                "A esquerda, em <b>Target:</b>, escolha <b>" + name + "</b> e "
                "clique em <b>Proximo</b>."
            ),
            note=(
                "Role o menu do OSAI ate o <b>" + name + "</b> aparecer antes de "
                "continuar."
            ),
            indicator=name,
        ),
        GuideStep(
            anchor="label@" + slug,
            title=name + ": capturar o nome",
            body=(
                "<ul>"
                "<li>Na imagem, arraste um retangulo "
                "<b>apertado em volta apenas do texto &quot;" + name + "&quot;</b>.</li>"
                "<li>Nao pegue a estrela nem o botao ON/OFF.</li>"
                "<li>Clique no botao verde abaixo.</li>"
                "</ul>"
            ),
            note=(
                "E assim que o app acha o indicador de novo depois que o menu e "
                "rolado para cima ou para baixo."
            ),
            requires=progress_key(name, REQ_LABEL),
            action=REQ_LABEL,
            needs_selection=True,
            indicator=name,
        ),
        GuideStep(
            anchor="toggle@" + slug,
            title=name + ": capturar o botao ON/OFF",
            body=(
                "<ul>"
                "<li>Arraste um retangulo em volta do <b>botao ON/OFF da mesma "
                "linha do " + name + "</b>.</li>"
                "<li>Clique no botao verde abaixo.</li>"
                "</ul>"
            ),
            requires=progress_key(name, REQ_TOGGLE),
            action=REQ_TOGGLE,
            needs_selection=True,
            indicator=name,
        ),
        GuideStep(
            anchor="on@" + slug,
            title=name + ": capturar como e LIGADO",
            body=(
                "<ul>"
                "<li>Na tela do OSAI, <b>ligue o " + name + "</b> (ON).</li>"
                "<li>Clique no botao verde abaixo. Desta vez nao precisa arrastar "
                "nada.</li>"
                "</ul>"
            ),
            note=(
                "Esta janela se esconde, tira uma foto nova e encontra o indicador "
                "sozinha."
            ),
            requires=progress_key(name, REQ_ON),
            action=REQ_ON,
            indicator=name,
        ),
        GuideStep(
            anchor="off@" + slug,
            title=name + ": capturar como e DESLIGADO",
            body=(
                "<ul>"
                "<li>Na tela do OSAI, <b>desligue o " + name + "</b> (OFF).</li>"
                "<li>Clique no botao verde abaixo.</li>"
                "</ul>"
            ),
            requires=progress_key(name, REQ_OFF),
            action=REQ_OFF,
            indicator=name,
        ),
    ]


def _steps_en(indicators: list[str]) -> list[GuideStep]:
    listed = ", ".join("<b>" + name + "</b>" for name in indicators)
    steps = [
        GuideStep(
            anchor="start",
            title="Before you start",
            body=(
                "<ul>"
                "<li>The OSAI screen must be visible behind this window.</li>"
                "<li>You will calibrate, in this order: " + listed + ".</li>"
                "</ul>"
                "When you are ready, click <b>Next</b>."
            ),
            note=(
                "This window hides itself for a moment every time it takes a "
                "picture, so it will not get in the way. Tip: the "
                "<b>Locks / Vacuum areas</b> panel on the other OSAI screen does "
                "not scroll - it is the safest place to calibrate."
            ),
        ),
    ]
    for name in indicators:
        steps.extend(_capture_steps_en(name))
    steps.extend(
        [
            GuideStep(
                anchor="iso",
                title="Capture the Iso lines field",
                body=(
                    "<ul>"
                    "<li>Drag a box around the <b>Iso lines</b> list at the "
                    "bottom left of the OSAI screen.</li>"
                    "<li>Include the whole list, not just one line.</li>"
                    "<li>Click the green button below.</li>"
                    "</ul>"
                ),
                note=(
                    "This is what tells the app a cut is about to start: OSAI "
                    "writes <b>CLOSE THE DOORS</b> there. If the text then "
                    "changes while the vacuum is off, the operator started "
                    "anyway - and that is recorded for the manager."
                ),
                requires=REQ_ISO,
                action=REQ_ISO,
                needs_selection=True,
            ),
            GuideStep(
                anchor="test",
                title="Test it",
                body=(
                    "Calibration is complete. Click <b>Done</b> and check the panel:"
                    "<ul>"
                    "<li>Switch each vacuum on and off - every line must show "
                    "<b>ON</b> (green) and <b>OFF</b> (red).</li>"
                    "<li>Scroll the OSAI menu until an indicator disappears - it "
                    "must show <b>NOT ON SCREEN</b> (orange).</li>"
                    "</ul>"
                ),
                warning=(
                    "If a line stays <b>NOT ON SCREEN</b> while the text is clearly "
                    "visible, come back and redo <b>capture the name</b> for that "
                    "indicator with a tighter box."
                ),
            ),
            GuideStep(
                anchor="backup",
                title="Back up the calibration",
                body=(
                    "Make a copy of <b>config.json</b> and of the "
                    "<b>assets\\templates</b> folder - both sit next to the program."
                ),
                note=(
                    "With those two, the calibration can be restored in seconds if "
                    "the PC is ever rebuilt."
                ),
            ),
            GuideStep(
                anchor="program",
                title="Optional: program name",
                body=(
                    "Drag a box where OSAI shows the file name (e.g. 4986_P4.CNC), "
                    "then click the green button below."
                ),
                note=(
                    "Optional: only used to show the name on the panel and in the "
                    "report. Click <b>Done</b> to finish."
                ),
                action=ACT_PROGRAM,
                needs_selection=True,
            ),
        ]
    )
    return steps


def _steps_pt(indicators: list[str]) -> list[GuideStep]:
    listed = ", ".join("<b>" + name + "</b>" for name in indicators)
    steps = [
        GuideStep(
            anchor="start",
            title="Antes de comecar",
            body=(
                "<ul>"
                "<li>A tela do OSAI precisa estar visivel atras desta janela.</li>"
                "<li>Voce vai calibrar, nesta ordem: " + listed + ".</li>"
                "</ul>"
                "Quando estiver pronto, clique em <b>Proximo</b>."
            ),
            note=(
                "Esta janela se esconde sozinha por um instante cada vez que tira "
                "uma foto, entao ela nao atrapalha. Dica: o painel "
                "<b>Locks / Vacuum areas</b> (na outra tela do OSAI) nao tem "
                "rolagem - e o lugar mais seguro para calibrar."
            ),
        ),
    ]
    for name in indicators:
        steps.extend(_capture_steps_pt(name))
    steps.extend(
        [
            GuideStep(
                anchor="iso",
                title="Capturar o campo Iso lines",
                body=(
                    "<ul>"
                    "<li>Arraste um retangulo em volta da lista <b>Iso lines</b>, "
                    "no canto inferior esquerdo da tela do OSAI.</li>"
                    "<li>Pegue a lista inteira, nao so uma linha.</li>"
                    "<li>Clique no botao verde abaixo.</li>"
                    "</ul>"
                ),
                note=(
                    "E por ali que o app sabe que um corte vai comecar: o OSAI "
                    "escreve <b>CLOSE THE DOORS</b> nesse campo. Se o texto mudar "
                    "com o vacuo desligado, o operador iniciou assim mesmo - e "
                    "isso fica registrado para o gerente."
                ),
                requires=REQ_ISO,
                action=REQ_ISO,
                needs_selection=True,
            ),
            GuideStep(
                anchor="test",
                title="Testar",
                body=(
                    "A calibracao esta completa. Clique em <b>Done</b> e confira no "
                    "painel:"
                    "<ul>"
                    "<li>Ligue e desligue cada vacuo - todas as linhas devem "
                    "mostrar <b>ON</b> (verde) e <b>OFF</b> (vermelho).</li>"
                    "<li>Role o menu do OSAI ate um indicador sumir - deve mostrar "
                    "<b>NOT ON SCREEN</b> (laranja).</li>"
                    "</ul>"
                ),
                warning=(
                    "Se uma linha ficar em <b>NOT ON SCREEN</b> com o texto bem "
                    "visivel, volte e refaca o <b>capturar o nome</b> daquele "
                    "indicador com o retangulo mais justo."
                ),
            ),
            GuideStep(
                anchor="backup",
                title="Guardar a calibracao",
                body=(
                    "Faca uma copia do arquivo <b>config.json</b> e da pasta "
                    "<b>assets\\templates</b> - os dois ficam junto do programa."
                ),
                note=(
                    "Com esses dois, a calibracao e restaurada em segundos se o PC "
                    "for formatado."
                ),
            ),
            GuideStep(
                anchor="program",
                title="Opcional: nome do programa",
                body=(
                    "Arraste um retangulo onde o OSAI mostra o arquivo (ex.: "
                    "4986_P4.CNC) e clique no botao verde abaixo."
                ),
                note=(
                    "Opcional: serve so para mostrar o nome no painel e no "
                    "relatorio. Clique em <b>Done</b> para terminar."
                ),
                action=ACT_PROGRAM,
                needs_selection=True,
            ),
        ]
    )
    return steps


# Wizard chrome text (header, buttons, checklist).
_UI = {
    "en": {
        "header": "Step {current} of {total}",
        "back": "< Back",
        "next": "Next >",
        "switch": "Portugues",
        "where": "Progress",
        "optional": " <i>(optional)</i>",
        "done_mark": "captured",
        "items": {
            REQ_LABEL: "Name (label)",
            REQ_TOGGLE: "ON/OFF button",
            REQ_ON: "ON sample",
            REQ_OFF: "OFF sample",
            REQ_ISO: "Iso lines area",
            ACT_PROGRAM: "Program name area",
        },
        "actions": {
            REQ_LABEL: "Capture the name",
            REQ_TOGGLE: "Capture the ON/OFF button",
            REQ_ON: "Capture ON sample",
            REQ_OFF: "Capture OFF sample",
            REQ_ISO: "Capture Iso lines area",
            ACT_PROGRAM: "Capture program name area",
        },
    },
    "pt": {
        "header": "Passo {current} de {total}",
        "back": "< Voltar",
        "next": "Proximo >",
        "switch": "English",
        "where": "Progresso",
        "optional": " <i>(opcional)</i>",
        "done_mark": "capturado",
        "items": {
            REQ_LABEL: "Nome (rotulo)",
            REQ_TOGGLE: "Botao ON/OFF",
            REQ_ON: "Amostra LIGADO",
            REQ_OFF: "Amostra DESLIGADO",
            REQ_ISO: "Area do campo Iso lines",
            ACT_PROGRAM: "Area do nome do programa",
        },
        "actions": {
            REQ_LABEL: "Capturar o nome",
            REQ_TOGGLE: "Capturar o botao ON/OFF",
            REQ_ON: "Capturar amostra LIGADO",
            REQ_OFF: "Capturar amostra DESLIGADO",
            REQ_ISO: "Capturar area do Iso lines",
            ACT_PROGRAM: "Capturar area do nome",
        },
    },
}


def build_steps(indicators, language: str = "en"):  # type: ignore[no-untyped-def]
    """The script, in the exact order the captures must happen.

    `indicators` is the list of names in calibration order (e.g.
    ["Vacuum Pump 1", "Vacuum 1"]). A single name is also accepted for
    convenience when there is only one indicator.
    """
    names = [indicators] if isinstance(indicators, str) else list(indicators)
    return _steps_pt(names) if language == "pt" else _steps_en(names)


@dataclass(frozen=True)
class ChecklistItem:
    text: str
    done: bool
    optional: bool = False
    group: str = ""  # indicator name; empty on general/optional items


def calibration_status(
    config: AppConfig, templates_dir: Path, language: str = "en"
) -> tuple[list[ChecklistItem], set[str]]:
    """Reads config and files, returning (items to show, keys already done).

    Progress is PER INDICATOR: calibrating Vacuum Pump 1 must not mark
    Vacuum 1 as done (nor the other way round). Keys are composite
    ("<slug>:<requirement>") - see progress_key().
    """
    texts = _UI.get(language, _UI["en"])
    names = texts["items"]

    done: set[str] = set()
    items: list[ChecklistItem] = []

    for indicator in config.indicators:
        slug = indicator.slug
        checks = [
            (REQ_LABEL, (templates_dir / (slug + "_label.png")).exists()),
            (REQ_TOGGLE, indicator.toggle is not None and indicator.toggle.is_valid()),
            (REQ_ON, (templates_dir / (slug + "_toggle_on.png")).exists()),
            (REQ_OFF, (templates_dir / (slug + "_toggle_off.png")).exists()),
        ]
        for requirement, is_done in checks:
            if is_done:
                done.add(progress_key(indicator.name, requirement))
            items.append(
                ChecklistItem(
                    text=names[requirement],
                    done=is_done,
                    optional=False,
                    group=indicator.name,
                )
            )

    if config.iso_roi is not None:
        done.add(REQ_ISO)
    items.append(ChecklistItem(names[REQ_ISO], config.iso_roi is not None, False))
    items.append(ChecklistItem(names[ACT_PROGRAM], config.program_roi is not None, True))
    return items, done


class CalibrationGuide(QWidget):
    """The wizard: one step at a time, one action button, real progress."""

    step_changed = Signal()

    def __init__(
        self,
        config: AppConfig,
        templates_dir: Path,
        parent: QWidget | None = None,
        on_language_changed: Callable[[str], None] | None = None,
        action_handler: Callable[[str, str], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._templates_dir = templates_dir
        self._on_language_changed = on_language_changed
        # The handler returns True when the capture worked - only then advance.
        self._action_handler = action_handler
        self._language = config.guide_language if config.guide_language in LANGUAGES else "en"
        self._steps = build_steps(self._indicator_names(), self._language)
        self._index = 0

        self._header = QLabel()
        self._header.setStyleSheet("color: #607d8b; font-weight: bold;")
        self._switch = QPushButton()
        self._switch.setToolTip("English / Portugues")
        self._switch.setMaximumWidth(110)
        self._switch.clicked.connect(self._toggle_language)
        top = QHBoxLayout()
        top.addWidget(self._header, 1)
        top.addWidget(self._switch)

        self._title = QLabel()
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-size: 14pt; font-weight: bold;")

        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.RichText)
        self._body.setAlignment(Qt.AlignTop)

        self._note = QLabel()
        self._note.setWordWrap(True)
        self._note.setTextFormat(Qt.RichText)
        self._note.setStyleSheet(
            "background: #eceff1; color: #37474f; border-radius: 4px; padding: 8px;"
        )

        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setTextFormat(Qt.RichText)
        self._warning.setStyleSheet(
            "background: #fff3e0; color: #e65100; border-radius: 4px; padding: 8px;"
        )

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._title)
        content_layout.addWidget(self._body)
        content_layout.addWidget(self._note)
        content_layout.addWidget(self._warning)
        content_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        # ONE action button per step: the heart of the simplification.
        self._action = QPushButton()
        self._action.setMinimumHeight(46)
        self._action.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; font-weight: bold;"
            "  font-size: 11pt; border-radius: 6px; padding: 10px; }"
            "QPushButton:hover { background-color: #388e3c; }"
        )
        self._action.clicked.connect(self._run_action)

        self._back = QPushButton()
        self._back.clicked.connect(lambda: self._go(self._index - 1))
        self._next = QPushButton()
        self._next.clicked.connect(lambda: self._go(self._index + 1))
        nav = QHBoxLayout()
        nav.addWidget(self._back)
        nav.addWidget(self._next)

        self._checklist = QLabel()
        self._checklist.setTextFormat(Qt.RichText)
        self._checklist.setWordWrap(True)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._action)
        layout.addLayout(nav)
        layout.addWidget(separator)
        layout.addWidget(self._checklist)

        self.setMinimumWidth(340)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self.refresh(jump_to_pending=True)

    # -- acao --------------------------------------------------------------

    def set_action_handler(self, handler: Callable[[str, str], bool]) -> None:
        self._action_handler = handler

    def _indicator_names(self) -> list[str]:
        """Names in config order - which is the order the wizard calibrates in."""
        return [ind.name for ind in self._config.indicators]

    def current_step(self) -> GuideStep:
        return self._steps[self._index]

    def _run_action(self) -> None:
        """Runs the step's action and only advances if the capture worked."""
        step = self.current_step()
        if not step.action or self._action_handler is None:
            return
        if self._action_handler(step.action, step.indicator):
            self.refresh()
            if self._index < len(self._steps) - 1:
                self._go(self._index + 1)

    # -- idioma ------------------------------------------------------------

    @property
    def language(self) -> str:
        return self._language

    def _toggle_language(self) -> None:
        """Switches EN <-> PT keeping the current step (the anchor is shared)."""
        anchor = self.current_step().anchor
        self._language = "pt" if self._language == "en" else "en"
        self._steps = build_steps(self._indicator_names(), self._language)
        self._index = next(
            (i for i, step in enumerate(self._steps) if step.anchor == anchor), self._index
        )
        self._config.guide_language = self._language
        if self._on_language_changed is not None:
            self._on_language_changed(self._language)
        self._render()

    # -- navegacao ---------------------------------------------------------

    def _go(self, index: int) -> None:
        self._index = max(0, min(index, len(self._steps) - 1))
        self._render()

    def _first_pending(self) -> int:
        """First step whose artefact is missing (or the test step, if complete)."""
        _, done = calibration_status(self._config, self._templates_dir, self._language)
        for position, step in enumerate(self._steps):
            if step.requires is not None and step.requires not in done:
                return position
        return next((i for i, step in enumerate(self._steps) if step.anchor == "test"), 0)

    def refresh(self, jump_to_pending: bool = False) -> None:
        """Re-reads progress from disk; optionally jumps to the pending step."""
        if jump_to_pending:
            self._index = self._first_pending()
        self._render()

    # -- desenho -----------------------------------------------------------

    def _render(self) -> None:
        texts = _UI[self._language]
        step = self.current_step()
        self._header.setText(
            texts["header"].format(current=self._index + 1, total=len(self._steps))
        )
        self._switch.setText(texts["switch"])
        self._back.setText(texts["back"])
        self._next.setText(texts["next"])
        self._title.setText(step.title)
        self._body.setText(step.body)
        self._note.setText(step.note)
        self._note.setVisible(bool(step.note))
        self._warning.setText(step.warning)
        self._warning.setVisible(bool(step.warning))

        # The green button only exists on steps that capture something.
        self._action.setVisible(bool(step.action))
        if step.action:
            self._action.setText(texts["actions"][step.action])

        self._back.setEnabled(self._index > 0)
        self._next.setEnabled(self._index < len(self._steps) - 1)
        self._render_checklist()
        self.step_changed.emit()

    def _render_checklist(self) -> None:
        texts = _UI[self._language]
        items, _ = calibration_status(self._config, self._templates_dir, self._language)
        rows = [
            "<b>" + texts["where"] + "</b>"
        ]
        # Grouped by indicator: with two vacuums, a flat list of eight items
        # would not say WHICH one each line refers to.
        group = ""
        for item in items:
            if item.group and item.group != group:
                group = item.group
                rows.append(f"<br><b>{group}</b>")
            if item.done:
                mark, colour = "OK", "#2e7d32"
            elif item.optional:
                mark, colour = "--", "#9e9e9e"
            else:
                mark, colour = "!!", "#c62828"
            suffix = texts["optional"] if item.optional and not item.done else ""
            rows.append(
                f"<span style='color:{colour}'><b>[{mark}]</b></span> {item.text}{suffix}"
            )
        self._checklist.setText("<br>".join(rows))


class CalibrationGuideDialog(QDialog):
    """The same script in its own window, read-only (captures nothing)."""

    def __init__(
        self,
        config: AppConfig,
        templates_dir: Path,
        on_language_changed: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Calibration guide - Vacuum Guardian")
        self.guide = CalibrationGuide(config, templates_dir, self, on_language_changed)
        # With no calibration window behind it there is nothing to capture: an
        # action button would only mislead the operator.
        self.guide._action.setVisible(False)
        self.guide._action.setEnabled(False)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(self.guide, 1)
        layout.addWidget(buttons)
        self.resize(470, 660)
