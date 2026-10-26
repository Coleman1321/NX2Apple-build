# NS Port Builder

A macOS front end that walks a new user through building a playable iOS IPA or macOS app from
their own Switch game files — the GUI counterpart of the repository's scripts.

<details>
<summary>Screenshot (click to expand)</summary>

<img src="screenshots/main-window-en.png" width="620" alt="NS Port Builder">

</details>

## What it does

- **Four inputs, picked separately**: base game, update, add-on content (DLC,
  multi-select) and `prod.keys`. `选整个文件夹…` still fills all four at once by
  title ID — `…000` is the base, `…800` the update, `base + 0x1000 + n` add-on
  content, and 0-byte files are skipped. When the files live in different
  folders the app stages them as symlinks in a temporary folder and passes the
  script `--work-dir`, so the extracted game files and the IPA still land next
  to the base game rather than in `/tmp`.
- **Dependency detection with one-click install**: Xcode + iOS SDK, the Metal
  Toolchain, Homebrew, `xcodegen` / `zstd` / `spirv-cross`, the .NET SDK and the
  Python packages. Every row shows ✓ / ✗ and, when missing, an 安装 button that
  runs the real installer (App Store for Xcode). `开始构建` stays disabled until
  every row is green, so a first build does not die halfway through.
- **Progress from the script's own stages**: the app parses the `[k/n]` lines
  `build_ipa_from_nsp.py --progress lines` writes, so the list follows the real
  plan (unpack, module rewrite, shader compile, IPA pack, archive) with a live
  percentage per stage, not a guessed five-step list.
- **Archive sharding** as the last step: the extracted RomFS goes through
  `dm/tools/romfs_arc.py` into a `romfs/` folder of ~200 MiB shards — named so it
  can be copied into the game app's `Documents/` unchanged. When the build
  finishes the window shows the three installation steps and a Reveal-in-Finder
  button for the IPA and the folder (see the [archive docs](../docs/ROMFS_ARCHIVE.md)).

## Build a Mac game app

Choose **Mac (.app)** in **Build for**, then build with the same game inputs and keys.
The GUI calls the existing nxnative `--platform mac-app` pipeline and writes
`<title ID>.app` beside the base game or in the selected output folder. It finishes
with a Reveal-in-Finder button; double-click the app to play or move it to Applications.
Game data, DLC and Mac shaders are included, so no separate RomFS archive is produced.
The app uses ad-hoc signing. Saves are kept in
`~/Library/Application Support/nxnative/<title ID>/`, and logs in
`~/Library/Logs/nxnative/<title ID>.log`.

The dependency panel follows the selected target: Mac builds require Xcode with the
macOS SDK and Metal toolchain, without requiring the iOS SDK or XcodeGen. Target and
input selection are locked while a build runs. iOS remains the default.

See [upstream packaging details](../docs/development.md#a-mac-app) for runtime
requirements, signing and command-line options.

## Run

```bash
cd frontend
swift run
```

or double-click `NS Port Builder.app` in this folder (ad-hoc signed; rebuild it
with `swift build -c release` and copy the binary into `Contents/MacOS/`).

SwiftUI, macOS 13+.

### Why the dependency check does not use `which`

A GUI app does not inherit the shell's PATH. On a machine where a terminal sees
`.NET` and the Python packages just fine, a naive `which dotnet` and
`/usr/bin/python3` check reports both missing. So the app looks where the tools
actually are (`~/.dotnet`, `/usr/local/share/dotnet`, the Python framework
installs), verifies `.NET` with `--list-sdks` (the extractor targets `net10.0`),
and picks the first interpreter that can really import
`lz4 capstone fontTools backports.zstd`. That same interpreter then runs the
build.

## Language

The interface follows the device on first launch: any Chinese variant (Simplified, Traditional,
Hong Kong, Taiwan) gets Chinese, **every other language gets English**. The `中文` / `EN` button in
the title bar switches between them at any time and the choice is remembered.

Every string lives in `Sources/NSPortBuilder/Localization.swift` as a `key: (Chinese, English)`
pair; a missing translation shows up as the raw key rather than a blank control, and
`L10n.selfCheck()` reports any empty side at launch.

## Notes

- The app discovers the checkout automatically; the repository panel can select another copy.
- It shells out to the same scripts the command line uses, so every option and
  limitation of the command line applies.
- Needs about 6 GB of free space beyond the NSPs for the extraction; the shader
  compile is the long step (~50 minutes for Tears of the Kingdom on an M-series
  Mac).
