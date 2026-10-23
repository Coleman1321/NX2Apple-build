# NS Port Builder v0.3.1 — release notes

This is the text of the [v0.3.1 release](https://github.com/LNPANDY/nxnative-romfs-archive/releases/tag/v0.3.1), which fixes issues [#1](https://github.com/LNPANDY/nxnative-romfs-archive/issues/1) and [#2](https://github.com/LNPANDY/nxnative-romfs-archive/issues/2). 中文说明在英文下方。

Two reported builds that failed on machines the first release never met: a Homebrew Python 3.15 and a Homebrew .NET. Both are fixed. Thank you @carbonimax for two excellent reports.

## Fixed: Python 3.14+ was rejected, and installs failed silently (#1)

- The dependency probe required `backports.zstd`, which declares Python < 3.14. Python 3.14 has `compression.zstd` built in, so a perfectly good Homebrew Python 3.15 was reported as missing packages. The probe now accepts either: `compression.zstd` where it exists, the backport where it does not.
- The 安装 button ran `pip install --user`, which Homebrew's externally-managed Python refuses under PEP 668 — and the output went to a pipe nobody read. Packages now install into a **dedicated virtual environment** (`~/Library/Application Support/NS Port Builder/venv`) created from the best interpreter found. Your system Python is never touched. `backports.zstd` is only installed where it is actually needed (before 3.14).
- Install output streams into the log window and a failure says so.

## Fixed: Homebrew dotnet built the extractor, then the extractor could not start (#2)

The app detected `/opt/homebrew/bin/dotnet` fine, then launched the build with a hardcoded `DOTNET_ROOT=~/.dotnet`. Homebrew's runtime lives in `…/opt/dotnet/libexec`, so the generated apphost found no runtime and `nx_extract` exited 131.

`DOTNET_ROOT` (and `DOTNET_ROOT_ARM64`) are now derived from the detected installation via `dotnet --list-runtimes`, which resolves symlinks and layout differences between Homebrew, the `.pkg` installer and `dotnet-install.sh`. The build script had the same bug in its own derivation; fixed there too.

## Verified

- The root parser handles Homebrew output, the standard `~/.dotnet` layout and backslash paths; the real `~/.dotnet` derives itself.
- A venv created from the package-less system Python 3.9 installs all four packages and passes the probe (PEP 668 never involved).
- A fake Homebrew tree (symlinked `bin`, runtime in `libexec`) derives `…/opt/dotnet/libexec`; the old code derived `…/bin`.

## Requirements (updated)

- An Apple Silicon Mac, macOS 13+
- **Python 3.9+** with `lz4`, `capstone`, `fontTools`, and zstd from `compression.zstd` (3.14+) or `backports.zstd` — the app's dependency panel manages a venv with all of this; you never pip-install by hand
- .NET SDK 10 — Homebrew, the .pkg installer and `dotnet-install.sh` all work now

---

# 中文说明

两个来自真实机器的构建失败：一台是 Homebrew 的 Python 3.15，一台是 Homebrew 的 .NET。都已修复。感谢 @carbonimax 的两份高质量报告。

## 修复：Python 3.14+ 被误判缺包，安装静默失败（#1）

- 依赖探针原来写死了 `backports.zstd`（它声明只支持 Python < 3.14），而 3.14 起标准库自带 `compression.zstd`，于是 Homebrew 的 Python 3.15 被误报缺包。现在两者都接受：有内置用内置，没有用 backport。
- 「安装」按钮原来跑 `pip install --user`，Homebrew 的受管 Python 会在 PEP 668 下拒绝——而且输出进了没人读的管道。现在包装进**专用虚拟环境**（`~/Library/Application Support/NS Port Builder/venv`），用检测到的最佳解释器创建，完全不碰系统 Python。`backports.zstd` 只在真正需要时（3.14 之前）安装。
- 安装输出实时进日志窗口，失败会明确提示。

## 修复：Homebrew 的 dotnet 能编译，但生成的程序起不来（#2）

App 检测 `/opt/homebrew/bin/dotnet` 正常，构建时却写死 `DOTNET_ROOT=~/.dotnet`。Homebrew 的运行时在 `…/opt/dotnet/libexec`，所以 apphost 找不到运行时，`nx_extract` 退出码 131。

现在 `DOTNET_ROOT`（和 `DOTNET_ROOT_ARM64`）通过 `dotnet --list-runtimes` 从检测到的安装推导，符号链接和 Homebrew / .pkg / dotnet-install.sh 三种布局都能解析。构建脚本里同样的推导也有同样的 bug，一并修复。

## 验证

- 根目录解析器覆盖 Homebrew 输出、标准 `~/.dotnet` 布局和反斜杠路径；真实 `~/.dotnet` 正确推导。
- 用无包的系统 Python 3.9 真实创建 venv，四个包全部装上且探针通过（全程未触碰 PEP 668）。
- 伪造 Homebrew 目录（bin 符号链接、运行时在 libexec）推导出 `…/opt/dotnet/libexec`；旧代码得到 `…/bin`。

## 环境要求（更新）

- Apple Silicon Mac，macOS 13+
- **Python 3.9+**，`lz4`、`capstone`、`fontTools`，以及 zstd（3.14+ 用内置的 `compression.zstd`，更早用 `backports.zstd`）——这些由 App 的依赖面板通过 venv 管理，不需要手动 pip
- .NET SDK 10 —— Homebrew、.pkg 安装器、dotnet-install.sh 三种方式都支持
