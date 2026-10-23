# NS Port Builder v0.3.0 — release notes

This is the text of the [v0.3.0 release](https://github.com/LNPANDY/nxnative-romfs-archive/releases/tag/v0.3.0); v0.2.1, v0.2.0 and v0.1.0 are in the git history. 中文说明在英文下方。

**The app now has an icon, and the repository follows upstream through 296 commits — 46 games instead of 19.**

<details>
<summary>Screenshot (click to expand)</summary>

<img src="../frontend/screenshots/main-window-en.png" width="620" alt="NS Port Builder">

</details>

## What's new in v0.3.0

**An app icon.** A green badge with a controller, in the same green as the app's header. The app is
no longer a blank square in the Dock and the Finder.

**46 game profiles, up from 19.** The repository was 296 upstream commits behind. Syncing brought
27 new titles, and the host and graphics work they need:

Hollow Knight: Silksong, Celeste, DARK SOULS: REMASTERED, Animal Crossing: New Horizons,
Paper Mario: The Thousand-Year Door, Pokémon Legends: Z-A, Luigi's Mansion 3, Super Mario Galaxy 2,
AI: THE SOMNIUM FILES, Cuphead, Catherine: Full Body, DRAGON QUEST XI S, DRAGON QUEST VII Reimagined,
FINAL FANTASY TACTICS, FINAL FANTASY RESONANCE, Monster Train 2, ANIMAL WELL, Raging Loop,
Digimon Story Cyber Sleuth, The Great Ace Attorney Chronicles, STEINS;GATE RE:BOOT,
Captain Toad: Treasure Tracker, Big Brain Academy, Patrick's Parabox, Absolum,
Brain Memory Training Academy, AI: nirvanA Initiative

That is the profile count, not a promise that every title boots. A profile carries a game's build
IDs, memory layout and shader tables; the host changes a game needs are part of the same upstream
work and came along with it. See the games table in the README for what is verified where.

**The fork's own features still work**, re-applied on top of the rewritten host:

- The RomFS archive layer, re-ported into the rewritten `hle_fs.c`. The host builds and the archive
  reader passes its test against a real two-shard archive.
- Slim IPA by default (`DM_FULL_ROMFS=1` for upstream's full package) and the placeholder ad-hoc
  signature that carries the Increased Memory Limit entitlement into a sideloader. Upstream now only
  sets that entitlement in its `--prepare-xcode` mode, so an IPA built from upstream alone would have
  lost it.
- `romfs.idx` recognition, `--work-dir`, and the `DOTNET_ROOT` derivation.

**The Python 3.9 fix from v0.2.1 is still in place**, and the new upstream code had three more of
the same problem (f-strings only Python 3.12 can parse). All fixed; every `.py` in the repository
parses under 3.9.

## What this build is

[`NS-Port-Builder-macOS-arm64.zip`](https://github.com/LNPANDY/nxnative-romfs-archive/releases/download/v0.3.0/NS-Port-Builder-macOS-arm64.zip)
— the app itself, ad-hoc signed, Apple Silicon, macOS 13+. Unzip it anywhere and double-click.
Because the signature is ad-hoc, the first launch needs right-click → Open, or
`xattr -dr com.apple.quarantine "NS Port Builder.app"`.

**This is a front end only.** It drives the scripts of
[nxnative-romfs-archive](https://github.com/LNPANDY/nxnative-romfs-archive), so you also need a
clone of that repository on the same Mac — and this release needs the current `main`, which carries
the 46 profiles. The app finds the checkout automatically when it sits next to it, and otherwise you
pick it once with Choose repository….

## Verified games

| Game | Status |
|---|---|
| **The Legend of Zelda: Tears of the Kingdom** (0100F2C0115B6000) | Verified — builds, installs and runs on an iPhone; 304,243 files into 127 archive shards, every file byte-verified |
| **Hades II** (0100A00019DE0000) | Verified — builds, installs and runs on an iPhone; 33-file archive |

**Every other game is unverified by this fork.** 20 of the 46 are reported playable on an iPhone by
upstream; the rest have a profile only. If you try another title, expect to bring it up yourself,
and please report what you find.

## Requirements

- An Apple Silicon Mac (the app is arm64 only; the build scripts also run on Intel)
- macOS 13 or later
- **Python 3.9 or newer** with `lz4`, `capstone`, `fonttools` and `backports.zstd`
- ~6 GB free beyond the NSPs for the extraction; the shader compile is the long step
- Your own game files and `prod.keys` — nothing is bundled

## Notes

- No game data, keys or firmware are included. Bring your own dumped NSPs.
- The command line remains the reference; every option and limitation documented in the repository
  applies here too.
- Sideloading to the phone (AltStore, Sideloadly, Xcode) is outside this app's scope — see
  `dm/ios/ENTITLEMENTS.md` for the memory-limit entitlement a large game needs.

---

# 中文说明

**App 有图标了，仓库同步了上游 296 个提交——游戏从 19 个增加到 46 个。**

## v0.3.0 新增

**App 图标。** 绿色圆角底 + 手柄图形，和 App 标题栏同一个绿色。Dock 和访达里不再是空白方块。

**46 个游戏 profile，原来 19 个。** 仓库落后上游 296 个提交，同步后新增 27 个游戏，以及它们需要的宿主和图形层改动：

Hollow Knight: Silksong, Celeste, DARK SOULS: REMASTERED, Animal Crossing: New Horizons,
Paper Mario: The Thousand-Year Door, Pokémon Legends: Z-A, Luigi's Mansion 3, Super Mario Galaxy 2,
AI: THE SOMNIUM FILES, Cuphead, Catherine: Full Body, DRAGON QUEST XI S, DRAGON QUEST VII Reimagined,
FINAL FANTASY TACTICS, FINAL FANTASY RESONANCE, Monster Train 2, ANIMAL WELL, Raging Loop,
Digimon Story Cyber Sleuth, The Great Ace Attorney Chronicles, STEINS;GATE RE:BOOT,
Captain Toad: Treasure Tracker, Big Brain Academy, Patrick's Parabox, Absolum,
Brain Memory Training Academy, AI: nirvanA Initiative

这是 profile 数量，不代表每个游戏都能跑起来。profile 提供 build ID、内存布局和 shader 表；游戏所需的宿主改动属于同一批上游工作，一并同步过来了。哪些验证到哪一步，见 README 的游戏表。

**本 fork 自己的功能都还在**，在重写后的宿主上重新落地：

- RomFS 归档层，重新移植进重写后的 `hle_fs.c`。宿主编译通过，归档读取器用真实的双分片归档跑通了测试。
- 默认瘦身 IPA（`DM_FULL_ROMFS=1` 才是上游的完整包），以及把「增加内存上限」entitlement 带进侧载工具的 ad-hoc 占位签名。上游现在只在 `--prepare-xcode` 模式下设这个 entitlement，直接用上游打出的 IPA 会丢掉它。
- `romfs.idx` 识别、`--work-dir`、`DOTNET_ROOT` 自动推导。

**v0.2.1 的 Python 3.9 修复仍在**，而且新同步的上游代码里又出现了三处同样的问题（只有 Python 3.12 能解析的 f-string），已全部修掉。仓库里每个 `.py` 都能被 3.9 解析。

## 这个包是什么

[`NS-Port-Builder-macOS-arm64.zip`](https://github.com/LNPANDY/nxnative-romfs-archive/releases/download/v0.3.0/NS-Port-Builder-macOS-arm64.zip) 就是 App 本身，ad-hoc 签名，Apple Silicon，macOS 13+。解压到任意位置双击即可。因为用的是 ad-hoc 签名，**首次启动需要右键 → 打开**，或者执行 `xattr -dr com.apple.quarantine "NS Port Builder.app"`。

**这只是前端。** 它调用 [nxnative-romfs-archive](https://github.com/LNPANDY/nxnative-romfs-archive) 里的脚本，所以这台 Mac 上还需要 clone 那个仓库——而且必须是带 46 个 profile 的当前 `main`。App 会自己找：放在仓库旁边能自动发现，找不到就用「Choose repository…」指定一次。

## 已验证的游戏

| 游戏 | 状态 |
|---|---|
| **塞尔达传说：王国之泪**（0100F2C0115B6000） | 已验证 —— 构建、安装、在 iPhone 上运行；304,243 个文件归档成 127 片，逐字节校验通过 |
| **Hades II**（0100A00019DE0000） | 已验证 —— 构建、安装、在 iPhone 上运行；33 个文件的归档 |

**其他游戏本 fork 均未验证。** 46 个里有 20 个是上游报告 iPhone 可玩的，其余只有 profile。如果你试了别的游戏，请做好自行 bring-up 的准备，也欢迎反馈结果。

## 环境要求

- Apple Silicon Mac（App 只有 arm64；构建脚本在 Intel 上也能跑）
- macOS 13 或更高
- **Python 3.9 或更新**，并装有 `lz4`、`capstone`、`fonttools`、`backports.zstd`
- 除 NSP 外额外预留约 6 GB 用于解包；shader 编译是最慢的一步
- 你自己的游戏文件和 `prod.keys` —— 包里不含任何游戏数据

## 注意事项

- 不含任何游戏数据、密钥或固件，请使用自己 dump 的 NSP。
- 命令行仍是权威；仓库里记录的所有选项和限制在这里同样适用。
- 往手机侧载（AltStore、Sideloadly、Xcode）不在这个 App 范围内 —— 大体积游戏需要的内存上限 entitlement 见 `dm/ios/ENTITLEMENTS.md`。
