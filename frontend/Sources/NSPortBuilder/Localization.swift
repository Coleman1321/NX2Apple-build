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
        "repo.notFound": ("未找到本项目——点右侧选择 clone 的位置",
                          "Project not found — pick your clone with the button"),
        "repo.notRepo": ("不是本项目的仓库：%@", "Not this project's repository: %@"),
        "repo.pickMessage": ("选择本项目（含 dm/tools/nx_extract/Program.cs）的文件夹",
                             "Pick this project's folder (the one holding dm/tools/nx_extract/Program.cs)"),

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
        "dep.title": ("设备依赖", "Device dependencies"),
        "dep.checking": ("检测中…", "Checking…"),
        "dep.allReady": ("全部就绪", "All ready"),
        "dep.missing": ("缺 %d 项", "%d missing"),
        "dep.recheck": ("重新检测", "Check again"),
        "dep.install": ("安装", "Install"),
        "dep.installing": ("安装中…", "Installing…"),
        "dep.openAppStore": ("打开 App Store", "Open App Store"),

        "dep.xcode": ("Xcode + iOS SDK", "Xcode + iOS SDK"),
        "dep.xcode.hint": ("App Store 安装，约 12 GB", "from the App Store, about 12 GB"),
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
        "dep.python": ("Python + 包", "Python + packages"),
        "dep.python.hint": ("lz4 capstone fonttools backports.zstd", "lz4 capstone fonttools backports.zstd"),
        "dep.python.missing": ("%@ 缺包", "%@ is missing packages"),
        "dep.install.fail": ("安装失败（退出码 %d），见下方日志", "Install failed (exit code %d) — see the log below"),
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
