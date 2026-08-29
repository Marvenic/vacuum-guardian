# Vacuum Guardian

Screen monitor for a CMS Brembana CNC (OSAI). It watches the OSAI screen and,
once the Iso lines field announces a cut is starting, checks that
**Vacuum 1** is ON. If it is OFF - or if it cannot be verified - it raises an
immediate visual and audible alarm.

The app **does not** modify OSAI and does not integrate with the CNC - it only
observes the screen.

## How it works

```
Capture the OSAI window (mss)
        v
Native Windows OCR on the Iso lines field (bottom left):
        "CLOSE THE DOORS"      -> DOORS   (about to cut)
        text changed after it  -> RUNNING (cutting)
Label search + colour -> state of Vacuum 1 anywhere on screen
        v
Rule engine:
        DOORS   + Vacuum 1 not ON      -> WARNING   (orange: still in time)
        RUNNING + Vacuum 1 OFF         -> CRITICAL  (red + override logged)
        RUNNING + not verifiable       -> WARNING   (orange)
        v
AlarmController -> popup + looping WAV + CSV audit trail
```

### Why the trigger is the Iso lines field

Every program on this machine is named `<number>.CNC`, so the name says
nothing about whether the job already started. The `Iso lines` list at the
bottom left does: OSAI writes **CLOSE THE DOORS** there once the file is
loaded, and replaces it with running code the moment the operator starts the
cut. Reading one small region also keeps a cycle cheap - the earlier
confirmation-dialog trigger needed OCR over the whole screen.

### Why "not visible" is an alarm too

The OSAI softkey menu scrolls, so `Vacuum 1` is not always on screen. Staying
quiet in that case would mean pretending everything is fine without having
checked anything - so it raises the orange alert instead. Being visible is
therefore part of the operating procedure. Keeping the fixed
`Locks / Vacuum areas` panel on screen (it does not scroll) avoids it.

Two reading modes per indicator:

| Mode | How | When to use |
|---|---|---|
| Scroll-proof | finds the **label** anywhere on screen, then reads the toggle beside it by **colour** | the softkey menu (it scrolls) |
| Fixed position | fixed ROI + ON/OFF templates | elements that never move |

An `UNKNOWN`/`NOT_VISIBLE` state never reports "ON" by omission - the worst
case is an orange alert, never silence.

## Running in development

Requires **Python 3.10** (the last version with an official PySide2 5.15 wheel).

```
py -3.10 -m venv .venv310
.venv310\Scripts\pip install -r requirements.txt
.venv310\Scripts\python main.py
```

Tests: `.venv310\Scripts\python -m pytest`

### Why Qt5 (PySide2) and not Qt6

The target is a CMS Brembana CNC controller running **Windows 10 Enterprise 2016
LTSB (build 1607)**. Every Qt6 release requires Windows 10 1809 or later, so
PySide6 fails to load there (`DLL load failed while importing QtCore`). Qt 5.15
supports Windows 7/8/10, and PySide2 is built without ICU, so the package does
not depend on the system's Unicode libraries - it is fully self-contained.

## Calibration (required before first use)

The calibration window is a **step-by-step wizard**: one instruction and one
green action button at a time, in capture order, with a progress checklist that
reads the real files on disk. Reopening it jumps straight to the first step
still missing. A `Portugues` / `English` switch changes the guide language
(this is the only bilingual text in the app; it is remembered in `config.json`).

On the machine, with the OSAI screen visible behind the window:

1. Click **Calibrate ROIs / Templates** and follow the wizard for `Vacuum 1`:
   capture the **name** (a tight box around the text), then the **ON/OFF
   button**, then an **ON sample** and an **OFF sample**.
2. For the samples there is nothing to drag: switch the vacuum on the OSAI
   screen and press the green button. The window hides itself, takes a fresh
   screenshot and finds the indicator on its own - no closing and reopening.
3. Capture the **Iso lines** field (required - it is the trigger). A final
   optional step stores the program-name area.

**Calibration guide** on the main window opens the same script read-only, for
reading before starting. **Advanced (manual buttons)** inside the calibration
window still exposes every action individually, including the fixed-position
mode, for out-of-order fixes.

Check on the panel that `Vacuum 1` switches between ON and OFF as you toggle
it, including after scrolling the menu. If it stays `NOT ON SCREEN` while the
label is clearly visible, redo the name step with a tighter box (or lower
`label_threshold` in `config.json`, 0.75 -> 0.65).

## Generated files

| Path | Contents |
|---|---|
| `config.json` | ROIs, monitored programs, threshold, interval |
| `logs/vacuum_guardian_YYYY-MM-DD.log` | diagnostic log (daily rotation, 30 days) |
| `logs/detections.csv` | audit trail: state transitions and alarms only |
| `logs/overrides.csv` | one line per program started with the vacuum off |
| `assets/templates/<slug>_label.png` | label image searched anywhere on screen |
| `assets/templates/<slug>_toggle_on/off.png` | colour samples of the two states |
| `assets/templates/<slug>_on/off.png` | ON/OFF templates (fixed-position mode) |

## Building the executable

```
.venv310\Scripts\python tools/build_release.py
```

This runs the whole release pipeline: icon -> PyInstaller -> operator guide ->
ZIP. Output in `dist\VacuumGuardian\` plus `dist\VacuumGuardian-portable.zip`.

## Portable distribution

Copy the `dist\VacuumGuardian` folder to the target machine - there is no
installer, and it needs neither Python nor administrator rights. The
`_internal` folder must travel with the `.exe`.

On first run the app creates, next to the `.exe`: `config.json`,
`assets\templates\` and `logs\`. The operator guide ships inside the package as
`READ ME - Quick start.txt`.

## Alarm channels

Two severities, deliberately different colours:

| Level | Colour | Meaning |
|---|---|---|
| CRITICAL | red | `Vacuum 1` is proven OFF while the program runs |
| WARNING | orange | `Vacuum 1` could not be verified (scrolled out of view) |

If an orange alert escalates to red, the sound comes back even if the operator
had silenced it - the situation got worse and staying muted would hide that.

The visual alarm is always active: a large popup (about 62% x 52% of the
screen, centred, always on top) that slowly pulses between two shades. It is
deliberately not full screen - the operator still sees the OSAI screen behind
it and keeps the context of the alarm.

The window size is proportional to the screen; the fonts are fixed in points,
which is a physical unit Qt already scales by monitor DPI - so the text keeps
the same real-world size on a Full HD or a 4K panel. The sound is optional - shops are noisy and CNC PCs
often have no speakers - and can be switched off in Settings. With sound off,
the "Silence" button is hidden, since there is nothing to silence.

The pulse is deliberately slow (~0.7 s per phase): fast flashing above 3 Hz is
uncomfortable and a photosensitivity risk.

## Automatic startup

Settings -> **Start automatically with Windows**. This creates a shortcut in
`shell:startup` (no administrator rights needed). Closing the window minimises
to the tray and monitoring continues. To quit for real, use **Exit** in the
tray menu.

## Language

All user-facing text (UI, alarms, logs, CSV headers, operator guide) is in
English. The single exception is the calibration guide, which the operator can
switch between English and Portuguese - it is the one screen a non-English
speaker has to follow step by step. Its language choice is stored in
`config.json` (`guide_language`). Source comments and docstrings are in
Portuguese.

## Future evolution

The architecture already isolates where the data comes from: `DetectionService`
produces a `DetectionResult` and `RuleEngine` decides on it. A direct PLC/OSAI
integration would only replace the source of that state (a new producer of
`DetectionResult`), leaving rules, alarm and UI untouched.

## Credits

Created by **Marcos Souza & Andrea Cursino** - Abilix Digital
<https://www.abilixdigital.com>
