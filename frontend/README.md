# NS Port Builder

A macOS front end that walks a new user through building a playable IPA from
their own Switch game files — the GUI counterpart of the repository's scripts.

## What it does

- Pick a game folder (scans for the base `[v0]` NSP, an update `[UPD]` NSP and
  `prod.keys`, showing a ✓ / ✗ row for each)
- One button runs the whole pipeline as subprocesses, with a live step list and
  the build log tail: 解包 → 模块改写 → shader 编译 → 瘦身 IPA → RomFS 归档分片
- On success the archive shards and the slim IPA sit next to the game files,
  ready for the Files-app copy onto the phone

## Run

```bash
cd frontend
swift run
```

SwiftUI, macOS 13+. The repo path is currently hardcoded in
`ContentView.swift` (`BuildModel.repo`) — point it at your checkout of this
repository. It shells out to the same scripts the command line uses, so every
option and limitation of the command line applies.
