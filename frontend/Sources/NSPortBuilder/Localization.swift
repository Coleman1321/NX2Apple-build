import Foundation

// The app's interface language. At first launch it follows the device: any Chinese variant
// (zh-Hans, zh-Hant, zh-HK, zh-TW…) gets Chinese, everything else gets English. The EN / 中文
// button in the title bar overrides that and the choice is remembered.
//
// Every user-visible string lives in the table below, so the two languages cannot drift apart:
// `L10n.selfCheck()` walks it at launch and logs any key that is empty on either side.

enum Lang: String {
    case zh, en

    /// The language to start in: the saved choice, else the device's.
    static func initial() -> Lang {
        if let saved = UserDefaults.standard.string(forKey: "uiLang"), let l = Lang(rawValue: saved) { return l }
        return device()
    }

    /// Chinese only when the device's first preferred language is Chinese; every other
    /// device gets English.
    static func device() -> Lang {
        guard let first = Locale.preferredLanguages.first?.lowercased() else { return .en }
        return first.hasPrefix("zh") ? .zh : .en
    }

    var other: Lang { self == .zh ? .en : .zh }

    /// What the toggle button says: the language you would switch to.
    var toggleLabel: String { self == .zh ? "EN" : "中文" }
}

enum L10n {
    /// key: (Chinese, English)
    static let table: [String: (zh: String, en: String)] = [
        // ---- title ----
        "app.subtitle": ("Switch 游戏 → iPhone IPA · 归档分片 · 大内存",
                         "Switch games → iPhone IPA · archive shards · large memory"),

        // ---- repository ----
        "repo.title": ("项目仓库", "Project repository"),
        "repo.note": ("App 调用这里的构建脚本", "the app runs the build scripts from here"),
        "repo.choose": ("选择仓库…", "Choose repository…"),
        "repo.notFound": ("未找到本项目——下载，或点右侧选择 clone 的位置",
                          "Project not found — download it, or pick your clone with the button"),
        "repo.notRepo": ("不是本项目的仓库：%@", "Not this project's repository: %@"),
        "repo.pickMessage": ("选择本项目（含 dm/tools/nx_extract/Program.cs）的文件夹",
                             "Pick this project's folder (the one holding dm/tools/nx_extract/Program.cs)"),
        "repo.download": ("下载仓库", "Download repository"),
        "repo.downloading": ("正在下载到 ~/NX2Apple…（进度见下方日志，约一分钟）",
                             "Downloading to ~/NX2Apple… (progress in the log below, about a minute)"),
        "repo.downloadDone": ("仓库已下载到 %@", "Repository downloaded to %@"),
        "repo.downloadFail": ("下载失败——网络不顺？用下面的手动方法",
                              "Download failed — flaky network? Use the manual route below"),
        "repo.manualHint": ("网络不顺也可以手动：打开", "Flaky network? Do it by hand: open"),
        "repo.manualHint2": ("→ 点绿色 Code 按钮 → Download ZIP，解压后点「选择仓库…」选中解压出的文件夹",
                             "→ the green Code button → Download ZIP, unzip, then pick the unzipped folder with Choose repository…"),
        "repo.noGit": ("这是 ZIP 下载的副本（无 git 历史），构建不受影响；点「接入 git」转为可更新",
                       "This is a ZIP copy (no git history); builds work fine — Make updatable connects it to git"),
        "repo.adopt": ("接入 git（可更新）", "Make updatable (git)"),
        "repo.adopting": ("正在接入 git…", "Connecting git…"),
        "repo.adopted": ("已接入 git，可以检查更新了", "Connected — updates work now"),
        "repo.adoptFail": ("接入失败——详情见日志", "Connect failed — see the log"),

        // ---- app self-update ----
        "app.checking": ("正在检查 App 更新…", "Checking for a new app version…"),
        "app.upToDate": ("App 已是最新版本", "The app is up to date"),
        "app.found": ("App 有新版本 %@，点右上角按钮更新", "A new version %@ is out — update from the top-right button"),
        "app.updateBtn": ("更新到 %@", "Update to %@"),
        "app.downloading": ("正在下载新版本…", "Downloading the new version…"),
        "app.installing": ("正在安装…（旧版本会进废纸篓）", "Installing… (the old version goes to the Trash)"),
        "app.relaunching": ("已更新到 %@，正在重启 App…", "Updated to %@ — restarting…"),
        "app.installFail": ("安装失败：%@——新版本已下载，可手动替换", "Install failed: %@ — the new version was downloaded; replace by hand"),
        "app.netFail": ("网络失败（GitHub 不通？稍后再试）", "Network failed (GitHub unreachable? try again later)"),
        "repo.destBusy": ("%@ 已存在且不是本项目——换个位置，或点「选择仓库…」",
                          "%@ already exists and is not this project — use another place, or Choose repository…"),
        "repo.firstHint": ("第一次用？点「下载仓库」自动获取项目（约一分钟，需要网络）",
                           "First time here? Download repository fetches the project for you (about a minute, needs network)"),
        "repo.update": ("检查并更新", "Check and update"),
        "repo.check": ("检查更新", "Check for updates"),
        "repo.checking": ("正在检查更新…", "Checking for updates…"),
        "repo.upToDate": ("已是最新版本", "Up to date"),
        "repo.behind": ("有更新：%d 个新提交，点「拉取更新」", "Updates available: %d new commits — pull them"),
        "repo.pull": ("拉取更新", "Pull updates"),
        "repo.pulling": ("正在更新…（构建不受影响，之前的构建文件不在仓库里）",
                         "Updating… (your builds are safe — their files live outside the repository)"),
        "repo.pulled": ("已更新到最新", "Updated to the latest"),
        "repo.pullFail": ("更新失败——详情见日志（本地文件被改过？）",
                          "Update failed — see the log (local changes?)"),
        "repo.gitInstalling": ("没找到 git，正在自动安装 PortableGit…（约 57 MB，无需管理员权限）",
                               "git not found — installing PortableGit… (about 57 MB, no administrator rights needed)"),
        "repo.gitInstallFail": ("git 自动安装失败：%@——可到 git-scm.com 手动安装",
                                "Could not install git: %@ — install it from git-scm.com"),
        "repo.gitMissing": ("没找到 git：Windows 请到 git-scm.com 下载安装，macOS 运行 xcode-select --install",
                            "git not found: install it from git-scm.com (Windows), or run xcode-select --install (macOS)"),
        "repo.netFail": ("检查更新失败（网络不通？）", "Could not check for updates (offline?)"),

        // ---- game data ----
        "data.title": ("游戏数据", "Game data"),
        "data.note": ("四项可以分开选", "four inputs, picked separately"),
        "data.pickFolder": ("选整个文件夹…", "Pick a folder…"),
        "data.folderHint": ("同一个文件夹里都有时，用右上角一次选好",
                            "When everything is in one folder, the button fills all four at once"),
        "data.base": ("游戏本体", "Base game"),
        "data.update": ("更新包", "Update"),
        "data.dlc": ("追加内容 DLC", "DLC (add-on)"),
        "data.keys": ("主机密钥 prod.keys", "prod.keys"),
        "data.notSelected": ("未选择", "Not selected"),
        "data.notSelectedOptional": ("未选择（可选）", "Not selected (optional)"),
        "data.files": ("%d 个文件：", "%d files: "),
        "data.clear": ("清除", "Clear"),
        "data.choose": ("选择…", "Choose…"),
        "data.change": ("更换…", "Change…"),
        "data.noBase": ("这个文件夹里没有本体 NSP（[xxxx…000]）",
                        "No base game NSP in this folder ([xxxx…000])"),
        "data.noNsp": ("这个文件夹里没有 NSP/XCI", "No NSP/XCI in this folder"),

        // ---- dependencies ----
        // ---- Qt front end (frontend-qt): keys the SwiftUI app does not use yet ----
        "build.start": ("开始构建", "Start build"),
        "build.cancel": ("取消构建", "Cancel build"),
        "msg.macAppDone": ("Mac App 已生成，可在访达里双击运行", "Mac app ready — double-click it in the Finder"),
        "msg.macAppMissing": ("构建结束但没有找到 .app（仓库里缺 dm/mac/pack_app.py？）",
                              "Build finished but no .app was produced (is dm/mac/pack_app.py in the checkout?)"),
        "opt.title": ("构建选项", "Build options"),
        "opt.note": ("按输出类型", "per output"),
        "opt.bc": ("兼容老设备（A15 / A16 及更早）", "Older devices (A15 / A16 and earlier)"),
        "opt.bc.note": ("在不支持 BC 纹理压缩的 GPU 上于 CPU 解压：iPhone 13 及更早、A16 的 iPad。新设备请保持关闭——GPU 路径更快",
                        "Decode BC textures on the CPU for GPUs without BC support: iPhone 13 and earlier, A16 iPads. Leave off on newer devices — the GPU path is faster"),
        "opt.macNoBc": ("Mac App 用这台 Mac 的 GPU，不需要兼容选项", "A Mac app uses this Mac's GPU; no compatibility option needed"),
        "msg.bcOn": ("兼容老设备：BC 纹理将在 CPU 上解压", "Older-device mode: BC textures will be decoded on the CPU"),
        "msg.bcEnvFailed": ("无法写入环境文件：%@——继续构建，但兼容模式未启用",
                            "Could not write the environment file: %@ — building without the compatibility mode"),
        "target.ios": ("输出：iPhone IPA", "Output: iPhone IPA"),
        "target.mac": ("输出：Mac App", "Output: Mac app"),
        "target.tip": ("点一下切换（Mac App 可直接双击运行，不需要 iPhone）",
                       "Click to switch (a Mac app runs on this Mac, no iPhone needed)"),
        "target.hint.ios": ("构建 iPhone 用的 IPA", "Building an IPA for an iPhone"),
        "target.hint.mac": ("构建可直接双击运行的 Mac App", "Building a double-clickable Mac app"),
        "target.macDone": ("Mac App 已生成，可在访达里双击运行", "Mac app ready — double-click it in the Finder"),
        "target.missingApp": ("构建结束但没有找到 .app 文件——看日志末尾", "Build finished but no .app was produced — see the end of the log"),
        "build.outDir": ("输出目录…", "Output folder…"),
        "msg.ipaAt": ("IPA：%@", "IPA: %@"),
        "msg.archiveAt": ("归档：%@", "Archive: %@"),
        "repo.ok": ("仓库可用", "repository ready"),
        "dep.iossdk": ("iPhoneOS SDK", "iPhoneOS SDK"),
        "dep.iossdk.hint": ("Windows 上需要 iPhoneOS SDK（用于交叉编译）",
                            "Windows needs an iPhoneOS SDK for the cross build"),
        "dep.metal.missing": ("未找到 metal.exe（Apple Metal Developer Tools for Windows）",
                              "metal.exe not found (Apple Metal Developer Tools for Windows)"),

        "dep.title": ("设备依赖", "Device dependencies"),
        "dep.checking": ("检测中…", "Checking…"),
        "dep.checkFailed": ("依赖检测失败——详情见日志（不是「已就绪」）", "Dependency check failed — see the log (this is not a pass)"),
        "dep.allReady": ("全部就绪", "All ready"),
        "dep.missing": ("缺 %d 项", "%d missing"),
        "dep.llvm": ("LLVM-MinGW（交叉编译）", "LLVM-MinGW (cross compiler)"),
        "dep.llvm.hint": ("Windows 上编译 iOS 二进制用（app 内自动下载）",
                          "builds the iOS binary on Windows (downloaded in-app)"),
        "dep.llvm.downloading": ("正在下载 LLVM-MinGW…（约 250 MB）", "Downloading LLVM-MinGW… (about 250 MB)"),
        "dep.llvm.done": ("LLVM-MinGW 已安装：%@", "LLVM-MinGW installed: %@"),
        "dep.hostArch": ("运行架构", "host architecture"),
        "dep.hostArch.hint": ("Windows on ARM 会用 x86-64 工具链模拟运行（较慢但可用）",
                              "Windows on ARM runs the x86-64 tools emulated (slower, works)"),
        "dep.lld": ("Mach-O 链接器（ld64.lld）", "Mach-O linker (ld64.lld)"),
        "dep.lld.hint": ("随 LLVM-MinGW 提供", "comes with LLVM-MinGW"),
        "dep.iossdk.downloading": ("正在下载 iPhoneOS SDK…（约 100 MB）",
                                   "Downloading the iPhoneOS SDK… (about 100 MB)"),
        "dep.iossdk.done": ("iPhoneOS SDK 已安装：%@", "iPhoneOS SDK installed: %@"),
        "dep.probe.compile": ("试编译 arm64 Mach-O", "trial compile to arm64 Mach-O"),
        "dep.probe.compile.hint": ("验证 clang 真能产出 iOS 目标文件",
                                   "checks that clang really produces iOS objects"),
        "dep.probe.link": ("试链接 iOS 可执行文件", "trial link to an iOS executable"),
        "dep.probe.link.hint": ("验证 ld64.lld 能链接", "checks that ld64.lld links"),
        "dep.probe.metal": ("试编译 Metal 着色器", "trial Metal shader compile"),
        "dep.probe.metal.hint": ("验证 metal.exe 能产出 metallib",
                                 "checks that metal.exe produces a metallib"),
        "dep.optionalMissing": ("可选，未安装", "optional, not installed"),
        "dep.glslang": ("glslangValidator（可选）", "glslangValidator (optional)"),
        "dep.glslang.hint": ("仅 OpenGL 游戏需要", "only needed for OpenGL games"),
        "dep.installTimeout": ("安装超时（30 分钟）——网络太慢或卡住了",
                                  "Install timed out (30 minutes) — the network is slow or stuck"),
        "dep.installAll": ("一键安装全部缺失项", "Install all missing"),
        "dep.recheck": ("重新检测", "Check again"),
        "dep.install": ("安装", "Install"),
        "dep.installing": ("安装中…", "Installing…"),
        "dep.openAppStore": ("打开 App Store", "Open App Store"),

        "dep.xcode": ("Xcode + iOS SDK", "Xcode + iOS SDK"),
        "dep.xcode.hint": ("App Store 安装，约 12 GB", "from the App Store, about 12 GB"),
        "dep.xcode.noSDK": ("Xcode 已装，但 iOS SDK 未下载（Xcode 15 起 iOS 平台是单独下载的）",
                            "Xcode is installed but the iOS SDK is not downloaded (a separate download since Xcode 15)"),
        "dep.metal": ("Metal Toolchain", "Metal Toolchain"),
        "dep.metal.hint": ("xcodebuild -downloadComponent MetalToolchain（约 840 MB）",
                           "xcodebuild -downloadComponent MetalToolchain (about 840 MB)"),
        "dep.brew": ("Homebrew", "Homebrew"),
        "dep.brew.hint": ("brew.sh（后续包的前置）", "brew.sh (needed by the packages below)"),
        "dep.xcodegen": ("brew: xcodegen", "brew: xcodegen"),
        "dep.xcodegen.hint": ("Xcode 工程生成", "generates the Xcode project"),
        "dep.zstd": ("brew: zstd", "brew: zstd"),
        "dep.zstd.hint": ("解压", "decompression"),
        "dep.spirv": ("brew: spirv-cross", "brew: spirv-cross"),
        "dep.spirv.hint": ("shader 转换", "shader translation"),
        "dep.dotnet": (".NET SDK 10", ".NET SDK 10"),
        "dep.dotnet.hint": ("dotnet-install.sh 装到 ~/.dotnet", "dotnet-install.sh into ~/.dotnet"),
        "dep.dotnet.missing": ("没找到带 SDK 10 的 dotnet", "no dotnet with SDK 10 found"),
        "dep.dotnet.downloading": ("正在下载 .NET SDK 10…（约 287 MB，解压后约 900 MB）", "Downloading .NET SDK 10… (about 287 MB, about 900 MB unpacked)"),
        "dep.dotnet.done": (".NET SDK 已安装：%@", ".NET SDK installed: %@"),
        "dep.phase.download": ("下载", "Download"),
        "dep.phase.unpack": ("解压", "Unpack"),
        "dep.python": ("Python + 包", "Python + packages"),
        "dep.python.hint": ("lz4 capstone fonttools backports.zstd", "lz4 capstone fonttools backports.zstd"),
        "dep.python.missing": ("%@ 缺包", "%@ is missing packages"),
        "dep.install.begin": ("开始安装 %@…", "Installing %@…"),
        "dep.install.fail": ("安装失败：%@（详情见日志）", "Install failed: %@ (see the log)"),
        "dep.python.old": ("Python %@ 太旧（需要 %@ 或更新）；系统的 /usr/bin/python3 没有这些包",
                           "Python %@ is too old (need %@ or newer); the system /usr/bin/python3 has none of these packages"),

        // ---- progress ----
        "prog.title": ("构建进度", "Build progress"),
        "prog.empty": ("开始构建后，这里显示脚本自己的每个阶段",
                       "The script's own stages appear here once the build starts"),
        "prog.archive": ("RomFS 归档分片（200 MiB/片）", "RomFS archive shards (200 MiB each)"),
        "prog.archiveShort": ("RomFS 归档分片", "RomFS archive shards"),
        "prog.noRomfs": ("找不到解出的 RomFS", "no extracted RomFS found"),

        // ---- log ----
        "log.export": ("导出日志…", "Export log…"),
        "log.exported": ("日志已保存：%@", "Log saved: %@"),
        "log.exportFail": ("保存失败：%@", "Could not save: %@"),
        "log.at": ("日志同时写入 %@", "The log is also written to %@"),
        "log.placeholder": ("构建日志会显示在这里", "The build log appears here"),

        // ---- footer ----
        "btn.build": ("开始构建", "Start build"),
        "btn.rebuild": ("重新构建", "Rebuild"),
        "btn.stop": ("停止", "Stop"),
        "btn.outDir": ("输出目录…", "Output folder…"),
        "status.checkingDeps": ("正在检测依赖…", "Checking dependencies…"),
        "status.installFirst": ("先安装上方缺失的依赖", "Install the missing dependencies above first"),
        "status.chooseRepo": ("先选择项目仓库", "Choose the project repository first"),
        "status.needInputs": ("还需要选择游戏本体和 prod.keys", "Still need the base game and prod.keys"),
        "status.output": ("输出：%@", "Output: %@"),
        "install.title": ("安装到 iPhone", "Install on the iPhone"),
        "install.step1": ("1\t用 AltStore / Sideloadly 安装上面的 IPA", "1\tInstall the IPA above with AltStore / Sideloadly"),
        "install.step2": ("2\t把上面的 romfs 文件夹整个拷到游戏 App 的 Documents 里（文件 App → 我的 iPhone → 游戏名）",
                          "2\tCopy the whole romfs folder above into the game app's Documents (Files → On My iPhone → game name)"),
        "install.step3": ("3\t启动游戏", "3\tLaunch the game"),
        "install.reveal": ("在访达中显示", "Reveal in Finder"),

        // ---- build messages ----
        "msg.running": ("运行：%@", "Running: %@"),
        "msg.installingNsz": ("选中的是 NSZ / XCZ 压缩格式，正在给构建用的 Python 安装 nsz…",
                              "The selected dump is NSZ / XCZ — installing nsz into the build's Python…"),
        "msg.noWorkDir": ("这个仓库不是 NX2Apple 的最新版本（构建脚本没有 --work-dir）：按脚本默认布局构建。建议换用 NX2Apple 仓库以获得归档复用与断点续传",
                          "This checkout is not the latest NX2Apple (its build script has no --work-dir): using the script's default layout. Switch to the NX2Apple repository for archive reuse and resumable builds"),
        "msg.nszFailed": ("nsz 安装失败（构建用的 Python：%@）——网络不通？或手动执行 pip install nsz",
                          "Could not install nsz (build Python: %@) — network trouble? Or run pip install nsz by hand"),
        "msg.stopped": ("已停止", "Stopped"),
        "msg.buildFailed": ("构建失败（退出码 %d），见下方日志",
                            "Build failed (exit code %d) — see the log below"),
        "msg.exitCode": ("退出码 %d", "exit code %d"),
        "msg.stagingFailed": ("无法在暂存文件夹里建立链接（文件在不同磁盘？）",
                              "Could not create links in the staging folder (files on different volumes?)"),
        "msg.launchFailed": ("无法启动构建脚本：%@", "Could not start the build script: %@"),
        "msg.repoInvalid": ("仓库路径无效：%@——用上方的「选择仓库…」指向本项目的 clone",
                            "Invalid repository path: %@ — use Choose repository… above to point at your clone"),
        "msg.repoInvalidEmpty": ("仓库路径无效：未选择——用上方的「选择仓库…」指向本项目的 clone",
                                 "Invalid repository path: none chosen — use Choose repository… above"),
        "msg.archiveSkipped": ("IPA 已生成，但归档跳过：找不到 %@/v*/RomFS",
                               "IPA built, archive skipped: no %@/v*/RomFS"),
        "msg.archiveFailed": ("归档失败（退出码 %d）", "Archive failed (exit code %d)"),
        "msg.archiveNoStart": ("无法启动 romfs_arc.py", "Could not start romfs_arc.py"),
        "msg.archiveIpaOnly": ("IPA 已生成，归档失败", "IPA built, but the archive failed"),
        "msg.done": ("完成：IPA 与 romfs 归档已生成，按下面三步装到手机", "Done: the IPA and the romfs archive are ready — three steps below"),
        "prog.archiveDone": ("归档就绪：%@", "archive ready: %@"),
        "prog.archiveReused": ("复用上次归档（%d 个文件未变）", "reused the previous archive (%d files unchanged)"),
        "msg.archiveReused": ("归档未变，复用 %@", "archive unchanged, reusing %@"),
        "msg.archiveLog": ("归档：%@ → %@", "Archive: %@ → %@"),
    ]

    static func string(_ key: String, _ lang: Lang) -> String {
        guard let row = table[key] else { return key }   // shows up in the UI rather than a blank control
        return lang == .zh ? row.zh : row.en
    }

    /// Every key has both languages and none is empty. Logged, never fatal.
    static func selfCheck() -> [String] {
        var bad: [String] = []
        for (key, row) in table where row.zh.isEmpty || row.en.isEmpty { bad.append(key) }
        return bad
    }
}
