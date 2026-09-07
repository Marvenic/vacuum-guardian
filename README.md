# Vacuum Guardian

Screen monitor for a **CMS Brembana CNC (OSAI)**. It watches the OSAI screen
and, when the operator is about to start a program, checks that **Vacuum 1** is
on. If it is off — or cannot be verified — it raises a visual and audible
alert. It only watches the screen: it does not modify OSAI and does not connect
to the CNC.

Free to use. Built by [Abilix Digital](https://www.abilixdigital.com).

## Download

Grab the `.zip` from the **[Releases](../../releases)** tab.

## Install (portable, no installer)

1. Extract `VacuumGuardian-portable.zip` into a **new, empty folder**
   (e.g. `C:\VacuumGuardian`).
2. Keep the `_internal` folder next to `VacuumGuardian.exe` — it is required.
3. Run `VacuumGuardian.exe`. No Python, no administrator rights.

When upgrading from an older version, **do not copy** `config.json` or the
`assets\templates` folder from the previous install: calibrate from scratch.

On first run the app creates, beside the `.exe`: `config.json`,
`assets\templates\` and `logs\`. The operator guide ships inside the package as
`READ ME - Quick start.txt`.

## How it decides (the Iso lines field)

The trigger is the **Iso lines** field at the bottom left of the OSAI screen —
it is the part that follows the program as it runs:

| Iso lines | What the app does |
|---|---|
| stand-by (irrelevant code) | silent |
| `CLOSE THE DOORS` and Vacuum 1 is not ON | **alert** — there is still time to switch it on |
| the text changes after that, with Vacuum 1 off | **alert** — the machine is already cutting |
| the text changes but Vacuum 1 cannot be read | **alert** — never silence without having checked |

Every start made with the vacuum off writes a line to `logs\overrides.csv`,
with date and time, so a manager can see whether the warning was ignored on
purpose.

The alert is a large orange pulsing window, always on top, with **one button**:
*Acknowledge*. It records the acknowledgement in `logs\alarm_actions.csv`,
frees the OSAI screen and **silences the alert for 5 minutes** — enough time to
walk to the machine without it popping back up. Monitoring does not stop during
that window, and switching the vacuum back on ends the silence immediately.
Sound is optional (noisy shops, PCs with no speakers) and can be turned off in
Settings — the visual alert never depends on it.

## Windows compatibility

Windows 10 and 11 (x64). The package is **self-contained**.

The interface uses **Qt 5 (PySide2)**, not Qt 6: this CNC controller runs
Windows 10 Enterprise 2016 LTSB (build 1607), and every Qt 6 release requires
Windows 10 1809 or newer — PySide6 fails there with *"DLL load failed while
importing QtCore"*. PySide2 is also built without ICU, so the package does not
depend on the system's Unicode libraries either.

## Calibration (before first use)

Done on the machine, with OSAI open. The app includes a **step-by-step wizard**
(switchable between English and Portuguese); the packaged
`READ ME - Quick start.txt` carries the same script.

1. **Settings** → enter part of the OSAI window title.
2. **Calibrate ROIs / Templates** → for each indicator (`Vacuum Pump 1`, then
   `Vacuum 1`) the wizard asks for the name, the ON/OFF button, and a sample of
   what ON and OFF look like.
3. **Capture the Iso lines area** — required: it is the alert trigger. Without
   it the app never fires.
4. Check the panel: the **Machine state** line should move between `stand-by`,
   `CLOSE THE DOORS - check vacuum` and `RUNNING - vacuum required`.

After calibrating, keep a copy of `config.json` and the `assets\templates`
folder — with those two the calibration is restored in seconds.

## Usage data (optional)

The app can send an anonymous usage report so we know which Windows versions
and regions to support, and how much it is actually used on a machine. It is
**off by default** and asks once, showing the exact JSON it would send.

- No screen contents, no program names, no file paths.
- The region comes from your own Windows setting, not from an IP lookup.
- Company, name, email and phone are an **optional** operator card; leave them
  empty and nothing personal is sent.
- Change your mind at any time: tray icon → **Usage data…**

`docs/telemetry-worker.js` is a ready-to-deploy Cloudflare Worker for the
receiving end.

## Generated files (beside the `.exe`)

| File | Contents |
|---|---|
| `config.json` | the calibration (regions, thresholds, indicators) |
| `assets\templates\` | learned images for each indicator |
| `logs\vacuum_guardian_YYYY-MM-DD.log` | daily technical log (kept 30 days) |
| `logs\detections.csv` | audit: every state change and every alert |
| `logs\overrides.csv` | short list: programs started with the vacuum off |
| `logs\alarm_actions.csv` | one line per Acknowledge click |

## Building from source

Requires **Python 3.10** (the last version with an official PySide2 5.15 wheel).

```
py -3.10 -m venv .venv310
.venv310\Scripts\pip install -r vacuum_guardian/requirements.txt
.venv310\Scripts\python vacuum_guardian/tools/build_release.py
```

Tests: `.venv310\Scripts\python -m pytest` from `vacuum_guardian/`.

---
Created by **Marcos Souza** — Abilix Digital ·
<https://www.abilixdigital.com>
