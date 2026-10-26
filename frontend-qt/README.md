# NS Port Builder — Qt front end (Windows and macOS)

The SwiftUI app in `../frontend/` is the macOS-native one. This is the **cross-platform**
counterpart: same job, same strings, built with PySide6 so Windows users get a native window.

## Why a second front end

The build pipeline (`scripts/build_ipa_from_nsp.py`) is Python and runs on both systems, but
the SwiftUI app cannot: it needs macOS. Rather than maintain two unrelated GUIs, this one is
written once and runs everywhere Python and Qt do.

| | SwiftUI (`frontend/`) | Qt (this) |
|---|---|---|
| Platforms | macOS 13+ | Windows 10+, macOS 11+ |
| Language | Swift | Python 3.9+ |
| Strings | `Localization.swift` | generated from that same file |
| Build logic | runs the Python scripts | runs the same scripts |

The strings are **generated** from the SwiftUI table (`gen_localization.py`), so the two front
ends cannot drift apart: edit `Localization.swift`, run the generator.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install PySide6            # Windows: .venv\Scripts\pip install PySide6
.venv/bin/python -m nspb_qt              # Windows: .venv\Scripts\python -m nspb_qt
```

From this folder. It looks for the repository checkout next to itself, in `~/NX2Apple`, or
wherever `NSPB_REPO` points, and the repository group lets you pick it by hand.

## What works today

- Dependency detection per platform: Python + packages, .NET SDK, and either **Xcode + iOS SDK +
  Metal toolchain** (macOS) or **iPhoneOS SDK + Apple's Metal Developer Tools** (Windows), plus
  xcodegen / zstd / spirv-cross. Each row has an install button when a command can fix it.
- Pick a game folder (or its four inputs separately); base / update / DLC / `prod.keys` are
  recognised from the dump names.
- Build: runs the same script the SwiftUI app runs, streams its stage lines and log, then packs
  the RomFS archive and reports where the IPA and archive landed.
- `--work-dir` is passed only when the checkout's script declares it (an upstream checkout has
  no such option — issue #5).
- Bilingual: Chinese on Chinese devices, English elsewhere; the header button switches.

## What is not there yet

- **The Windows build path is untested.** The platform layer is written (tool discovery, the
  SDK/Metal checks, `CREATE_NO_WINDOW` for child processes) but no Windows machine has run it.
  The cross-compile steps themselves live in the WebUI-style toolchain, not here yet.
- No self-update, no repository download/update buttons (the SwiftUI app has both).
- No per-stage progress bar, no cancel-with-cleanup (cancel terminates the child).

## Layout

```
nspb_qt/
  __main__.py       entry point
  model.py          state, dependency detection, build runner (Qt signals, no widgets)
  ui.py             the window
  platform_util.py  per-OS paths, tool discovery, child environment
  i18n.py           language choice
  localization.py   generated from ../frontend/Sources/NSPortBuilder/Localization.swift
gen_localization.py regenerates localization.py
```
