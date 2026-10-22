# NS Port Builder v0.2.0 — release notes

This is the text of the [v0.2.0 release](https://github.com/LNPANDY/nxnative-romfs-archive/releases/tag/v0.2.0). The v0.1.0 notes are kept in the git history. 中文说明在英文下方。

Bilingual interface: the app now speaks English, and Chinese only when your device does.

<details>
<summary>Screenshot (click to expand)</summary>

<img src="../frontend/screenshots/main-window-en.png" width="620" alt="NS Port Builder">

</details>

## What's new in v0.2.0

**The interface is bilingual.** Before this release it was Chinese-only, which shut out anyone who
does not read Chinese.

- **It follows your device.** On first launch, any Chinese variant (Simplified, Traditional, Hong
  Kong, Taiwan) gets Chinese; **every other language gets English.**
- **`中文` / `EN` in the title bar** switches at any time. The button shows the language you would
  switch *to*, and the choice is remembered across launches.
- All 78 user-visible strings live in one table as `key: (Chinese, English)` pairs. A missing
  translation renders as the key itself rather than a blank button, and a self-check reports any
  empty side at launch.
- Values that carry data — a missing package's path, exit codes, the archive destination — are
  translated as whole sentences with placeholders, so word order stays right in both languages.
- Switching language re-renders the dependency rows and game-data slots immediately; it does not
  disturb a running build.

Also in this release: the label column no longer wraps ("Add-on content (DLC)" broke onto two lines
at the old width), and the download now includes English and Chinese screenshots.

Everything else is unchanged from v0.1.0: four inputs picked separately, dependency detection with
one-click install, progress parsed from the script's own stage lines, and automatic RomFS archive
shards.

## What this build is

[`NS-Port-Builder-macOS-arm64.zip`](https://github.com/LNPANDY/nxnative-romfs-archive/releases/download/v0.2.0/NS-Port-Builder-macOS-arm64.zip)
— the app itself, ad-hoc signed, Apple Silicon, macOS 13+. Unzip it anywhere and double-click.
Because the signature is ad-hoc, the first launch needs right-click → Open, or
`xattr -dr com.apple.quarantine "NS Port Builder.app"`.

**This is a front end only.** It drives the scripts of
[nxnative-romfs-archive](https://github.com/LNPANDY/nxnative-romfs-archive), so you also need a
clone of that repository on the same Mac. The app finds it automatically when it sits next to the
checkout, and otherwise you pick it once with Choose repository… (the row turns green when the
folder is a real checkout — it contains `dm/tools/nx_extract/Program.cs`).

## Verified games

| Game | Status |
|---|---|
| **The Legend of Zelda: Tears of the Kingdom** (0100F2C0115B6000, v1.0.0 + update 1.4.3) | Verified — builds, installs and runs on an iPhone; 304,243 files packed into 127 archive shards, every file byte-verified against the source |
| **Hades II** (0100A00019DE0000, base + update) | Verified — builds, installs and runs on an iPhone; 33-file archive |

**Every other game is unverified.** nxnative needs a per-game profile (`dm/games/<title ID>/`) and,
for a game without one, the build falls back to a survey plus a provisional profile whose values
are guessed — it may not boot. If you try another title, expect to bring it up yourself, and please
report what you find.

## Requirements

- An Apple Silicon Mac (the app is arm64 only; the build scripts themselves also run on Intel)
- macOS 13 or later
- ~6 GB free beyond the NSPs for the extraction; the shader compile is the long step (~50 minutes
  for Tears of the Kingdom)
- Your own game files and `prod.keys` — nothing is bundled

## Notes

- No game data, keys or firmware are included. Bring your own dumped NSPs.
- The app is a convenience wrapper; the command line remains the reference. Every option and
  limitation documented in the repository applies here too.
- Sideloading to the phone (AltStore, Sideloadly, Xcode) is outside this app's scope — see
  `dm/ios/ENTITLEMENTS.md` for the memory-limit entitlement that a large game needs.

---

# 中文说明

界面双语化：现在支持英文，只有设备是中文时才显示中文。

## v0.2.0 新增

**界面支持中英双语。** 在此之前只有中文，把不看中文的人挡在了外面。

- **跟随设备语言。** 首次启动时，任何中文变体（简体、繁体、香港、台湾）都用中文，**其他所有语言一律英文**。
- **标题栏的 `中文` / `EN` 按钮**随时切换。按钮显示的是你**将要切换到的**语言，选择会被记住。
- 全部 78 条界面文案集中在同一张表里，每条都是 `key: (中文, 英文)` 配对。缺少翻译时会直接显示 key 本身而不是空白按钮，启动时还会自检并报告哪一边为空。
- 带数据的文案——缺失的包路径、退出码、归档目标目录——整句翻译并用占位符替换，保证两种语言的语序都正确。
- 切换语言会立即重新渲染依赖列表和游戏数据槽位，不会干扰正在运行的构建。

本次还包括：标签列不再折行（`Add-on content (DLC)` 在原来的宽度下会断成两行），下载包内附中英文两版截图。

其余功能与 v0.1.0 相同：四项输入分开选、依赖检测与一键安装、从脚本自身阶段行解析的进度、自动生成 RomFS 归档分片。

## 这个包是什么

[`NS-Port-Builder-macOS-arm64.zip`](https://github.com/LNPANDY/nxnative-romfs-archive/releases/download/v0.2.0/NS-Port-Builder-macOS-arm64.zip) 就是 App 本身，ad-hoc 签名，Apple Silicon，macOS 13+。解压到任意位置双击即可。因为用的是 ad-hoc 签名，**首次启动需要右键 → 打开**，或者执行 `xattr -dr com.apple.quarantine "NS Port Builder.app"`。

**这只是前端。** 它调用的是 [nxnative-romfs-archive](https://github.com/LNPANDY/nxnative-romfs-archive) 里的脚本，所以这台 Mac 上还需要 clone 那个仓库。App 会自己找：放在仓库旁边能自动发现，找不到就用「Choose repository…」指定一次（目录里有 `dm/tools/nx_extract/Program.cs` 才算真正的仓库，那一行会变绿）。

## 已验证的游戏

| 游戏 | 状态 |
|---|---|
| **塞尔达传说：王国之泪**（0100F2C0115B6000，v1.0.0 + 更新 1.4.3） | 已验证 —— 构建、安装、在 iPhone 上运行；304,243 个文件归档成 127 片，逐字节校验全部通过 |
| **Hades II**（0100A00019DE0000，本体 + 更新） | 已验证 —— 构建、安装、在 iPhone 上运行；33 个文件的归档 |

**其他游戏均未验证。** nxnative 需要每个游戏自己的 profile（`dm/games/<title ID>/`）；没有 profile 时会退化成「调研 + 推测参数」的临时 profile，**可能无法启动**。如果你试了别的游戏，请做好自行 bring-up 的准备，也欢迎把结果反馈过来。

## 环境要求

- Apple Silicon Mac（App 只有 arm64；构建脚本本身在 Intel 上也能跑）
- macOS 13 或更高
- 除 NSP 外额外预留约 6 GB 空间用于解包；shader 编译是最慢的一步（王国之泪约 50 分钟）
- 你自己的游戏文件和 `prod.keys` —— 包里不含任何游戏数据

## 注意事项

- 不含任何游戏数据、密钥或固件，请使用自己 dump 的 NSP。
- 这个 App 只是便捷封装，命令行仍是权威；仓库里记录的所有选项和限制在这里同样适用。
- 往手机侧载（AltStore、Sideloadly、Xcode）不在这个 App 的范围内 —— 大体积游戏需要的内存上限 entitlement 见 `dm/ios/ENTITLEMENTS.md`。
