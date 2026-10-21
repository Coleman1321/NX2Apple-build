import SwiftUI

// NS Port Builder: a macOS front end that walks a user through building a playable
// IPA from their own Switch game files. Not part of the host runtime; drives the
// repository's scripts (build_ipa_from_nsp.py, romfs_arc.py) as subprocesses.
//
// The four inputs are picked separately — base game, update, add-on content (DLC),
// prod.keys — because they are not always in one folder. When they are (the common
// case) the folder is passed straight to the script; otherwise a staging folder of
// symlinks is built and the script's --work-dir keeps the real build folder next to
// the base game.

// MARK: - Pieces

struct Stage: Identifiable {
    let id: Int          // k, the stage number in the script's own plan
    var name: String
    var state: StepState = .running
    var detail: String = ""
    var percent: Double? = nil
}

enum StepState: Equatable {
    case pending, running, done, failed
    var icon: String {
        switch self {
        case .pending: return "circle"
        case .running: return "spinner"
        case .done: return "checkmark.circle.fill"
        case .failed: return "xmark.octagon.fill"
        }
    }
    var color: Color {
        switch self {
        case .pending: return .gray
        case .running: return .orange
        case .done: return .green
        case .failed: return .red
        }
    }
}

/// One of the four things the user points at.
enum InputKind { case base, update, dlc, keys }

struct Slot: Identifiable {
    let id: String
    let kind: InputKind
    let title: String
    let optional: Bool
    var paths: [String] = []
    var problem: String = ""
    var ok: Bool { paths.contains { FileManager.default.fileExists(atPath: $0) } }
    var summary: String {
        if !problem.isEmpty { return problem }
        if paths.isEmpty { return optional ? "未选择（可选）" : "未选择" }
        if paths.count == 1 { return (paths[0] as NSString).lastPathComponent }
        return "\(paths.count) 个文件：" + paths.map { ($0 as NSString).lastPathComponent }.joined(separator: "、")
    }
}

// MARK: - Model

final class BuildModel: ObservableObject {
    @Published var gameDir = ""
    @Published var slots: [Slot] = [
        Slot(id: "base", kind: .base, title: "游戏本体", optional: false),
        Slot(id: "update", kind: .update, title: "更新包", optional: true),
        Slot(id: "dlc", kind: .dlc, title: "追加内容 DLC", optional: true),
        Slot(id: "keys", kind: .keys, title: "主机密钥 prod.keys", optional: false),
    ]
    @Published var outDir = ""
    @Published var stages: [Stage] = []
    @Published var running = false
    @Published var logTail = ""
    @Published var done = false
    @Published var doneNote = ""

    @Published var deps: [Dep] = []
    @Published var depsChecked = false
    @Published var pythonPath = ""

    private var proc: Process?
    private var lineBuf = ""
    private var staging: String?

    /// The checkout of this repository the app drives. A released .app ships on its own,
    /// so the path is not known at build time: look next to the app bundle, walk up from
    /// it, then fall back to a saved choice. A repository is identified by
    /// dm/tools/nx_extract/Program.cs, which only exists in a real checkout.
    @Published var repoPath: String = BuildModel.findRepo() {
        didSet { UserDefaults.standard.set(repoPath, forKey: "repoPath") }
    }

    nonisolated static func isRepo(_ dir: String) -> Bool {
        FileManager.default.fileExists(atPath: dir + "/dm/tools/nx_extract/Program.cs")
    }

    nonisolated static func findRepo() -> String {
        if let saved = UserDefaults.standard.string(forKey: "repoPath"), isRepo(saved) { return saved }
        var seeds: [String] = []
        // the app bundle: …/frontend/NS Port Builder.app/Contents/MacOS
        let bundle = Bundle.main.bundleURL.standardizedFileURL
        seeds.append(bundle.deletingLastPathComponent().deletingLastPathComponent()
                         .deletingLastPathComponent().deletingLastPathComponent().path)
        seeds.append(FileManager.default.currentDirectoryPath)
        seeds.append(NSHomeDirectory() + "/ZCodeProject/nxnative-romfs-archive")
        seeds.append(NSHomeDirectory() + "/nxnative-romfs-archive")
        seeds.append(NSHomeDirectory() + "/Documents/nxnative-romfs-archive")
        seeds.append(NSHomeDirectory() + "/Desktop/nxnative-romfs-archive")
        var seen = Set<String>()
        for s in seeds where !s.isEmpty && seen.insert(s).inserted {
            var d = s
            for _ in 0..<5 {                       // walk up a few levels from each seed
                if isRepo(d) { return d }
                let up = (d as NSString).deletingLastPathComponent
                if up == d || up == "/" { break }
                d = up
            }
        }
        return ""
    }

    var basePath: String { slot("base").paths.first ?? "" }
    var keysPath: String { slot("keys").paths.first ?? "" }
    var updatePath: String { slot("update").paths.first ?? "" }
    var dlcPaths: [String] { slot("dlc").paths }

    func slot(_ id: String) -> Slot { slots.first { $0.id == id } ?? slots[0] }
    private func updateSlot(_ id: String, _ body: (inout Slot) -> Void) {
        if let i = slots.firstIndex(where: { $0.id == id }) { body(&slots[i]) }
    }

    // MARK: Inputs

    /// Fill every slot from a folder: NSP/XCI classified by title ID (…000 base,
    /// …800 update, anything above base+0x1000 add-on content), plus prod.keys.
    func scan(folder: String) {
        gameDir = folder
        let fm = FileManager.default
        let names = (try? fm.contentsOfDirectory(atPath: folder)) ?? []
        var base: [String] = [], update: [String] = [], dlc: [String] = []
        for n in names.sorted() {
            let low = n.lowercased()
            guard low.hasSuffix(".nsp") || low.hasSuffix(".xci") else { continue }
            let path = folder + "/" + n
            guard ((try? fm.attributesOfItem(atPath: path))?[.size] as? Int ?? 0) > 0 else { continue }
            guard let tid = Self.titleID(n) else { continue }
            switch tid & 0xFFF {
            case 0: base.append(path)
            case 0x800: update.append(path)
            default: dlc.append(path)
            }
        }
        updateSlot("base") { $0.paths = Array(base.prefix(1)); $0.problem = base.isEmpty ? "这个文件夹里没有本体 NSP（[xxxx…000]）" : "" }
        updateSlot("update") { $0.paths = Array(update.prefix(1)); $0.problem = "" }
        updateSlot("dlc") { $0.paths = dlc; $0.problem = "" }
        if let k = names.first(where: { $0 == "prod.keys" }) { updateSlot("keys") { $0.paths = [folder + "/" + k]; $0.problem = "" } }
        if base.isEmpty && update.isEmpty && dlc.isEmpty {
            updateSlot("base") { $0.problem = "这个文件夹里没有 NSP/XCI" }
        }
    }

    func pickFiles(kind: InputKind) {
        let p = NSOpenPanel()
        p.canChooseDirectories = false
        p.canChooseFiles = true
        p.allowsMultipleSelection = (kind == .dlc)
        switch kind {
        case .base, .update: p.allowedFileTypes = ["nsp", "xci"]
        case .dlc: p.allowedFileTypes = ["nsp"]
        case .keys: p.allowedFileTypes = ["keys"]
        }
        guard p.runModal() == .OK, !p.urls.isEmpty else { return }
        let id = kind == .base ? "base" : kind == .update ? "update" : kind == .dlc ? "dlc" : "keys"
        let picked = p.urls.map(\.path)
        updateSlot(id) { s in
            s.paths = kind == .dlc ? Array(Set(s.paths + picked)).sorted() : Array(picked.prefix(1))
            s.problem = ""
        }
        if kind == .base, !picked.isEmpty { gameDir = (picked[0] as NSString).deletingLastPathComponent }
    }

    func clear(_ id: String) { updateSlot(id) { $0.paths = []; $0.problem = "" } }

    /// The title ID in a file name: [0100F2C0115B6000]
    nonisolated static func titleID(_ name: String) -> UInt64? {
        guard let re = try? NSRegularExpression(pattern: #"\[([0-9A-Fa-f]{16})\]"#) else { return nil }
        let ns = name as NSString
        guard let m = re.firstMatch(in: name, range: NSRange(location: 0, length: ns.length)) else { return nil }
        return UInt64(ns.substring(with: m.range(at: 1)), radix: 16)
    }

    var repoOK: Bool { Self.isRepo(repoPath) }
    var canBuild: Bool { repoOK && !basePath.isEmpty && !keysPath.isEmpty && allDepsPresent && !running }

    // MARK: Build

    func startBuild() {
        running = true; done = false; doneNote = ""; stages = []; logTail = ""; lineBuf = ""
        guard repoOK else { fail("仓库路径无效：\(repoPath.isEmpty ? "未选择" : repoPath)——用上方的「选择仓库…」指向本项目的 clone"); return }
        let py = pythonPath.isEmpty ? "/usr/bin/python3" : pythonPath

        // One folder when everything lives together; otherwise a staging folder of symlinks.
        let baseDir = (basePath as NSString).deletingLastPathComponent
        let allPaths = [basePath, updatePath] + dlcPaths
        let dirs = Set(allPaths.filter { !$0.isEmpty }.map { ($0 as NSString).deletingLastPathComponent })
        var inputDir = baseDir
        if dirs.count > 1 {
            let tmp = NSTemporaryDirectory() + "nsport-\(UUID().uuidString.prefix(8))"
            try? FileManager.default.createDirectory(atPath: tmp, withIntermediateDirectories: true)
            var linked = 0
            for f in allPaths where !f.isEmpty {
                let dst = tmp + "/" + (f as NSString).lastPathComponent
                if (try? FileManager.default.createSymbolicLink(atPath: dst, withDestinationPath: f)) != nil { linked += 1 }
            }
            if linked == 0 { fail("无法在暂存文件夹里建立链接（文件在不同磁盘？）"); return }
            staging = tmp; inputDir = tmp
        } else { staging = nil }

        let tidHex = Self.titleID(basePath).map { String(format: "%016llX", $0) } ?? "game"
        let workDir = (outDir.isEmpty ? baseDir : outDir) + "/" + tidHex + "_build"
        var args = [repoPath + "/scripts/build_ipa_from_nsp.py", inputDir, "-k", keysPath,
                    "--work-dir", workDir, "--progress", "lines"]
        if !outDir.isEmpty { args += ["-o", outDir + "/" + tidHex + ".ipa"] }
        say("运行：\(py) " + args.joined(separator: " "))

        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = args
        p.currentDirectoryURL = URL(fileURLWithPath: repoPath)
        p.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                         "DOTNET_ROOT": NSHomeDirectory() + "/.dotnet",
                         "USER": NSUserName(), "HOME": NSHomeDirectory(), "LANG": "en_US.UTF-8"]
        let pipe = Pipe()
        p.standardOutput = pipe; p.standardError = pipe
        p.terminationHandler = { [weak self] status in
            DispatchQueue.main.async {
                guard let self else { return }
                self.running = false
                self.flushLines()
                if status.terminationStatus == 0 {
                    self.markAllDone()
                    self.packArchive(workDir: workDir)   // keeps running=true until the archive is done
                } else {
                    if let i = self.stages.lastIndex(where: { $0.state == .running }) {
                        self.stages[i].state = .failed
                        self.stages[i].detail = "退出码 \(status.terminationStatus)"
                    } else { self.doneNote = "构建失败（退出码 \(status.terminationStatus)），见下方日志" }
                    self.cleanupStaging()
                }
            }
        }
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            guard !d.isEmpty, let s = String(data: d, encoding: .utf8) else { return }
            DispatchQueue.main.async { self?.ingest(s) }
        }
        proc = p
        do { try p.run() } catch { fail("无法启动构建脚本：\(error.localizedDescription)") }
    }

    private func fail(_ why: String) { running = false; doneNote = why; say("✗ " + why); cleanupStaging() }

    func stop() {
        proc?.terminate(); running = false
        doneNote = "已停止"; cleanupStaging()
    }

    private func cleanupStaging() {
        if let s = staging { try? FileManager.default.removeItem(atPath: s); staging = nil }
    }

    private func markAllDone() { for i in stages.indices where stages[i].state != .failed { stages[i].state = .done } }

    // MARK: Output parsing

    private func say(_ s: String) { append(s + "\n") }
    private func append(_ s: String) {
        logTail += s
        if logTail.count > 12000 { logTail = String(logTail.suffix(9000)) }
    }

    /// Split into lines (the pipe delivers arbitrary chunks) and turn the script's
    /// progress lines into the stage list. `--progress lines` writes:
    ///   [12:00:01] [2/7] extract v720896 …
    ///   [12:00:09] [2/7] extract v720896: 45%, 1.2/3.4 GB, 0:08
    ///   [12:00:20] ✓ [2/7] extract v720896 (0:19): 30,000 files, 3.4 GB
    private func ingest(_ chunk: String) {
        lineBuf += chunk
        while let i = lineBuf.firstIndex(of: "\n") {
            let line = String(lineBuf[..<i]).replacingOccurrences(of: "\r", with: "")
            lineBuf = String(lineBuf[lineBuf.index(after: i)...])
            handle(line)
        }
    }

    private func flushLines() {
        guard !lineBuf.isEmpty else { return }
        handle(lineBuf); lineBuf = ""
    }

    private func handle(_ line: String) {
        append(line + "\n")
        guard let s = Self.parseStage(line) else { return }
        if let i = stages.firstIndex(where: { $0.id == s.k }) {
            if !s.name.isEmpty { stages[i].name = s.name }
            if s.state != .pending { stages[i].state = s.state }
            if !s.detail.isEmpty { stages[i].detail = s.detail }
            stages[i].percent = s.percent
        } else if s.state != .pending {
            stages.append(Stage(id: s.k, name: s.name, state: s.state, detail: s.detail, percent: s.percent))
            stages.sort { $0.id < $1.id }
        }
    }

    nonisolated static func parseStage(_ line: String) -> (k: Int, name: String, state: StepState, detail: String, percent: Double?)? {
        guard let re = try? NSRegularExpression(pattern: #"\[(\d+)/(\d+)\] (.+)$"#) else { return nil }
        let ns = line as NSString
        guard let m = re.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) else { return nil }
        guard let k = Int(ns.substring(with: m.range(at: 1))) else { return nil }
        var rest = ns.substring(with: m.range(at: 3))

        if let pct = rest.range(of: #"(\d+)%"#, options: .regularExpression) {
            let v = Double(rest[pct].dropLast()) ?? 0
            var name = String(rest[..<pct.lowerBound]).trimmingCharacters(in: CharacterSet(charactersIn: " :·"))
            if let dot = name.range(of: " · ", options: .backwards) { name = String(name[..<dot.lowerBound]) }
            let after = String(rest[pct.upperBound...]).trimmingCharacters(in: CharacterSet(charactersIn: ", :"))
            return (k, name, .running, after, v)
        }
        let ok = line.contains("✓"), bad = line.contains("✗")
        if ok || bad {
            var detail = ""
            if let r = rest.range(of: "): ") { detail = String(rest[r.upperBound...]); rest = String(rest[..<r.lowerBound]) + ")" }
            if let r = rest.range(of: " (", options: .backwards) { rest = String(rest[..<r.lowerBound]) }
            return (k, rest, bad ? .failed : .done, detail, 100)
        }
        if rest.hasSuffix(" …") { rest = String(rest.dropLast(2)) }
        if let dot = rest.range(of: " · ", options: .backwards), !rest.hasPrefix("survey") { rest = String(rest[..<dot.lowerBound]) }
        return (k, rest, .running, "", nil)
    }

    // MARK: Archive

    /// Pack the extracted RomFS into a ROMFSARC archive. The extracted folder is
    /// <work>/extract/v<N>/RomFS where N is the profile's package version, so take
    /// the highest v* that actually has a RomFS instead of hardcoding one game.
    private func packArchive(workDir: String) {
        let fm = FileManager.default
        let extract = workDir + "/extract"
        let vers = ((try? fm.contentsOfDirectory(atPath: extract)) ?? [])
            .filter { $0.hasPrefix("v") && fm.fileExists(atPath: extract + "/" + $0 + "/RomFS") }
            .sorted { (Int($0.dropFirst()) ?? 0) < (Int($1.dropFirst()) ?? 0) }
        guard let v = vers.last else {
            stages.append(Stage(id: 1000, name: "RomFS 归档分片", state: .failed, detail: "找不到解出的 RomFS"))
            doneNote = "IPA 已生成，但归档跳过：找不到 \(extract)/v*/RomFS"
            cleanupStaging(); return
        }
        let romfs = extract + "/" + v + "/RomFS"
        let dest = (outDir.isEmpty ? (basePath as NSString).deletingLastPathComponent : outDir) + "/archive"
        try? fm.createDirectory(atPath: dest, withIntermediateDirectories: true)
        let idx = 1000
        stages.append(Stage(id: idx, name: "RomFS 归档分片（200 MiB/片）", state: .running, detail: v))
        say("归档：\(romfs) → \(dest)/romfs.idx")

        let p = Process()
        p.executableURL = URL(fileURLWithPath: pythonPath.isEmpty ? "/usr/bin/python3" : pythonPath)
        p.arguments = [repoPath + "/dm/tools/romfs_arc.py", "pack", romfs, dest + "/romfs", "--shard-mib", "200"]
        p.environment = ["PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "PYTHONPATH": repoPath + "/dm/tools"]
        let pipe = Pipe(); p.standardOutput = pipe; p.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            guard !d.isEmpty, let s = String(data: d, encoding: .utf8) else { return }
            DispatchQueue.main.async { self?.append(s) }
        }
        p.terminationHandler = { [weak self] st in DispatchQueue.main.async {
            guard let self else { return }
            self.cleanupStaging()
            if let i = self.stages.firstIndex(where: { $0.id == idx }) {
                self.stages[i].state = st.terminationStatus == 0 ? .done : .failed
                self.stages[i].detail = st.terminationStatus == 0 ? dest + "/romfs.idx" : "归档失败（退出码 \(st.terminationStatus)）"
            }
            let n = ((try? FileManager.default.contentsOfDirectory(atPath: dest)) ?? []).filter { $0.hasPrefix("romfs") }.count
            self.running = false
            self.done = st.terminationStatus == 0
            self.doneNote = st.terminationStatus == 0
                ? "完成：IPA + 归档 \(n) 个文件（\(dest)）"
                : "IPA 已生成，归档失败"
        }}
        do { try p.run() } catch {
            if let i = stages.firstIndex(where: { $0.id == idx }) { stages[i].state = .failed; stages[i].detail = "无法启动 romfs_arc.py" }
            running = false; doneNote = "IPA 已生成，归档失败"; cleanupStaging()
        }
    }

    // MARK: Dependencies

    struct Dep: Identifiable {
        let id: String
        let name: String
        let hint: String
        var present: Bool
        var installing = false
        var detail = ""
        let installCmd: [String]      // run via bash; empty = manual (Xcode from the App Store)
    }

    /// A GUI app does not inherit the shell's PATH, so look where the tools actually
    /// live instead of trusting `which` — that is why .NET (in ~/.dotnet) and the
    /// Python packages (in /usr/local/bin/python3, not /usr/bin/python3) used to show
    /// as missing while a terminal could see them.
    nonisolated static func runOK(_ tool: String, _ args: [String], env: [String: String]? = nil) -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: tool)
        p.arguments = args
        if let env { p.environment = env }
        p.standardOutput = Pipe(); p.standardError = Pipe()
        p.standardInput = FileHandle.nullDevice
        do { try p.run() } catch { return false }
        p.waitUntilExit()
        return p.terminationStatus == 0
    }

    nonisolated static func firstExisting(_ paths: [String]) -> String? {
        paths.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    /// The Python that actually has lz4/capstone/fontTools/backports.zstd — the one
    /// the build must run under, not whatever /usr/bin/python3 happens to be.
    nonisolated static func findPython() -> (path: String, ok: Bool) {
        var cands: [String] = []
        let fw = "/Library/Frameworks/Python.framework/Versions"
        if let vers = try? FileManager.default.contentsOfDirectory(atPath: fw) {
            for v in vers.sorted(by: { $0.compare($1, options: .numeric) == .orderedDescending }) {
                cands.append(fw + "/" + v + "/bin/python3")
            }
        }
        cands += ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        p.arguments = ["-a", "python3"]
        let pipe = Pipe()
        p.standardOutput = pipe; p.standardError = Pipe()
        p.standardInput = FileHandle.nullDevice
        if (try? p.run()) != nil {
            p.waitUntilExit()
            let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            cands += out.split(separator: "\n").map(String.init)
        }
        var seen = Set<String>()
        for c in cands where !c.isEmpty && seen.insert(c).inserted {
            guard FileManager.default.isExecutableFile(atPath: c) else { continue }
            if runOK(c, ["-c", "import lz4, capstone, fontTools, backports.zstd"]) { return (c, true) }
        }
        return (cands.first { FileManager.default.isExecutableFile(atPath: $0) } ?? "/usr/bin/python3", false)
    }

    nonisolated static func findDotnet() -> (path: String, ok: Bool) {
        let cands = [NSHomeDirectory() + "/.dotnet/dotnet",
                     "/usr/local/share/dotnet/dotnet",
                     "/opt/homebrew/bin/dotnet",
                     "/usr/local/bin/dotnet"]
        if let d = firstExisting(cands) {
            // the extractor targets net10.0, so an SDK (not just a runtime) is needed
            let ok = runOK(d, ["--list-sdks"], env: ["DOTNET_ROOT": (d as NSString).deletingLastPathComponent,
                                                      "PATH": "/usr/bin:/bin", "HOME": NSHomeDirectory()])
            return (d, ok)
        }
        return ("dotnet", false)
    }

    nonisolated static func detectDepsSync() -> [Dep] {
        var out: [Dep] = []

        let xcode = FileManager.default.fileExists(atPath: "/Applications/Xcode.app")
            && FileManager.default.isExecutableFile(atPath: "/usr/bin/xcodebuild")
        out.append(Dep(id: "xcode", name: "Xcode + iOS SDK", hint: "App Store 安装，约 12 GB",
                       present: xcode, installCmd: []))

        let mt = runOK("/usr/bin/xcrun", ["-sdk", "macosx", "metal", "--version"])
        out.append(Dep(id: "metal", name: "Metal Toolchain", hint: "xcodebuild -downloadComponent MetalToolchain（约 840 MB）",
                       present: mt, installCmd: ["xcodebuild", "-downloadComponent", "MetalToolchain"]))

        let brew = firstExisting(["/opt/homebrew/bin/brew", "/usr/local/bin/brew"])
        out.append(Dep(id: "brew", name: "Homebrew", hint: "brew.sh（后续包的前置）", present: brew != nil,
                       installCmd: ["/bin/bash", "-c",
                         "NONINTERACTIVE=1 /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""]))
        for (pkg, hint) in [("xcodegen", "Xcode 工程生成"), ("zstd", "解压"), ("spirv-cross", "shader 转换")] {
            let path = firstExisting(["/opt/homebrew/bin/\(pkg)", "/usr/local/bin/\(pkg)"])
            out.append(Dep(id: "brew:" + pkg, name: "brew: " + pkg, hint: hint, present: path != nil,
                           detail: path ?? "",
                           installCmd: [(brew ?? "/opt/homebrew/bin/brew"), "install", pkg]))
        }

        let (dn, dnOK) = findDotnet()
        out.append(Dep(id: "dotnet", name: ".NET SDK 10", hint: "dotnet-install.sh 装到 ~/.dotnet",
                       present: dnOK, detail: dnOK ? dn : "没找到带 SDK 10 的 dotnet",
                       installCmd: ["/bin/bash", "-c",
                         "curl -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/di.sh && chmod +x /tmp/di.sh && /tmp/di.sh --channel 10.0 --install-dir $HOME/.dotnet"]))

        let (py, pyOK) = findPython()
        out.append(Dep(id: "python", name: "Python + 包", hint: "lz4 capstone fonttools backports.zstd",
                       present: pyOK, detail: pyOK ? py : "\(py) 缺包",
                       installCmd: [py, "-m", "pip", "install", "--user", "lz4", "capstone", "fonttools", "backports.zstd"]))
        return out
    }

    func checkDeps() {
        depsChecked = false
        DispatchQueue.global(qos: .userInitiated).async {
            let d = Self.detectDepsSync()
            let (py, pyOK) = Self.findPython()
            DispatchQueue.main.async {
                self.deps = d
                self.pythonPath = pyOK ? py : "/usr/bin/python3"
                self.depsChecked = true
            }
        }
    }

    func installDep(_ dep: Dep) {
        guard !dep.installCmd.isEmpty else {
            NSWorkspace.shared.open(URL(fileURLWithPath: "/Applications/App Store.app"))
            return   // Xcode comes from the App Store; the user re-checks when it is done
        }
        guard let i = deps.firstIndex(where: { $0.id == dep.id }) else { return }
        deps[i].installing = true
        let cmd = dep.installCmd
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/bash")
            p.arguments = ["-c", cmd.map { $0.contains(" ") ? "'" + $0 + "'" : $0 }.joined(separator: " ")]
            p.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                             "HOME": NSHomeDirectory(), "NONINTERACTIVE": "1", "USER": NSUserName()]
            p.standardOutput = Pipe(); p.standardError = Pipe()
            p.standardInput = FileHandle.nullDevice
            try? p.run(); p.waitUntilExit()
            DispatchQueue.main.async {
                if let j = self.deps.firstIndex(where: { $0.id == dep.id }) { self.deps[j].installing = false }
                self.checkDeps()
            }
        }
    }

    var allDepsPresent: Bool { depsChecked && deps.allSatisfy { $0.present } }
}

// MARK: - View

struct ContentView: View {
    @StateObject private var m: BuildModel

    init(model: BuildModel? = nil) {
        _m = StateObject(wrappedValue: model ?? BuildModel())
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView(.vertical, showsIndicators: true) { sections }
            Divider()
            footer
        }
        .frame(minWidth: 720, idealWidth: 880, minHeight: 560, idealHeight: 820)
        .onAppear { m.checkDeps() }
    }

    // The scrollable part, split out so it can be rendered on its own for layout checks.
    var sections: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            repository
            inputs
            dependencies
            stagesView
            logView
        }
        .padding(.horizontal, 22)
        .padding(.top, 20)
        .padding(.bottom, 18)
    }

    // ---- 标题 ----

    private var header: some View {
        HStack(spacing: 14) {
            Image(systemName: "gamecontroller.fill")
                .font(.system(size: 28))
                .foregroundStyle(.white)
                .frame(width: 54, height: 54)
                .background(RoundedRectangle(cornerRadius: 13, style: .continuous).fill(Color.green.gradient))
            VStack(alignment: .leading, spacing: 3) {
                Text("NS Port Builder").font(.system(size: 25, weight: .bold))
                Text("Switch 游戏 → iPhone IPA · 归档分片 · 大内存")
                    .font(.system(size: 13)).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
    }

    /// Show the home directory as ~ — shorter in a one-line row, and it keeps the
    /// account name out of screenshots.
    private func short(_ path: String) -> String {
        let home = NSHomeDirectory()
        return path.hasPrefix(home) ? "~" + path.dropFirst(home.count) : path
    }

    private func sectionHeader(_ symbol: String, _ title: String, note: String = "") -> some View {
        HStack(spacing: 8) {
            Image(systemName: symbol).font(.system(size: 14, weight: .semibold)).foregroundStyle(.secondary)
            Text(title).font(.system(size: 15, weight: .semibold))
            if !note.isEmpty { Text(note).font(.system(size: 11.5)).foregroundStyle(.tertiary) }
            Spacer(minLength: 0)
        }
    }

    // ---- 仓库 ----

    private var repository: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    sectionHeader("shippingbox", "项目仓库", note: "App 调用这里的构建脚本")
                    Button("选择仓库…") { pickRepo() }
                }
                HStack(spacing: 10) {
                    Image(systemName: m.repoOK ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .font(.system(size: 15))
                        .foregroundStyle(m.repoOK ? Color.green : Color.red)
                        .frame(width: 20)
                    Text(m.repoOK ? short(m.repoPath)
                         : (m.repoPath.isEmpty ? "未找到本项目——点右侧选择 clone 的位置" : "不是本项目的仓库：\(short(m.repoPath))"))
                        .font(.system(size: 12.5, design: .monospaced))
                        .foregroundStyle(m.repoOK ? Color.secondary : Color.orange)
                        .lineLimit(1).truncationMode(.head)
                        .help(m.repoPath)
                    Spacer(minLength: 8)
                }
            }.padding(8)
        }
    }

    private func pickRepo() {
        let d = NSOpenPanel()
        d.canChooseDirectories = true; d.canChooseFiles = false
        d.message = "选择本项目（含 dm/tools/nx_extract/Program.cs）的文件夹"
        if d.runModal() == .OK, let u = d.url { m.repoPath = u.path }
    }

    // ---- 游戏数据 ----

    private var inputs: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    sectionHeader("folder", "游戏数据", note: "四项可以分开选")
                    Button("选整个文件夹…") { pickFolder() }
                }
                Text(m.gameDir.isEmpty ? "同一个文件夹里都有时，用右上角一次选好" : short(m.gameDir))
                    .font(.system(size: 11.5, design: .monospaced))
                    .foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
                VStack(spacing: 9) {
                    ForEach(m.slots, id: \.id) { s in
                        HStack(spacing: 10) {
                            Image(systemName: s.ok ? "checkmark.circle.fill" : (s.optional ? "circle.dashed" : "xmark.circle.fill"))
                                .font(.system(size: 15))
                                .foregroundStyle(s.ok ? Color.green : (s.optional ? Color.secondary : Color.red))
                                .frame(width: 20)
                            Text(s.title).font(.system(size: 14)).frame(width: 140, alignment: .leading)
                            Text(s.summary)
                                .font(.system(size: 12.5, design: .monospaced))
                                .lineLimit(1).truncationMode(.middle)
                                .foregroundStyle(s.ok ? Color.secondary : Color.orange)
                                .help(s.paths.joined(separator: "\n"))
                            Spacer(minLength: 8)
                            if !s.paths.isEmpty { Button("清除") { m.clear(s.id) }.controlSize(.small) }
                            Button(s.paths.isEmpty ? "选择…" : "更换…") { m.pickFiles(kind: s.kind) }
                        }
                    }
                }
            }.padding(8)
        }
    }

    private func pickFolder() {
        let d = NSOpenPanel()
        d.canChooseDirectories = true; d.canChooseFiles = false
        if d.runModal() == .OK, let u = d.url { m.scan(folder: u.path) }
    }

    // ---- 设备依赖 ----

    private var dependencies: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    sectionHeader("wrench.and.screwdriver", "设备依赖")
                    if !m.depsChecked {
                        ProgressView().controlSize(.small)
                        Text("检测中…").font(.system(size: 12)).foregroundStyle(.secondary)
                    } else if m.allDepsPresent {
                        Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                        Text("全部就绪").font(.system(size: 12, weight: .medium)).foregroundStyle(.green)
                    } else {
                        Text("缺 \(m.deps.filter { !$0.present }.count) 项")
                            .font(.system(size: 12, weight: .medium)).foregroundStyle(.orange)
                    }
                    Button("重新检测") { m.checkDeps() }.controlSize(.small)
                }
                VStack(spacing: 7) {
                    ForEach(m.deps, id: \.id) { d in
                        HStack(spacing: 10) {
                            if d.installing {
                                ProgressView().controlSize(.small).frame(width: 20)
                            } else {
                                Image(systemName: d.present ? "checkmark.circle.fill" : "xmark.circle.fill")
                                    .font(.system(size: 14))
                                    .foregroundStyle(d.present ? Color.green : Color.red)
                                    .frame(width: 20)
                            }
                            Text(d.name).font(.system(size: 13.5)).frame(width: 140, alignment: .leading)
                            Text(short(d.detail.isEmpty ? d.hint : d.detail))
                                .font(.system(size: 11.5, design: .monospaced))
                                .foregroundStyle(.secondary)
                                .lineLimit(1).truncationMode(.middle).help(d.hint)
                            Spacer(minLength: 8)
                            if d.installing {
                                Text("安装中…").font(.system(size: 11.5)).foregroundStyle(.orange)
                            } else if !d.present {
                                Button(d.installCmd.isEmpty ? "打开 App Store" : "安装") { m.installDep(d) }
                                    .controlSize(.small)
                            }
                        }
                    }
                }
            }.padding(8)
        }
    }

    // ---- 构建进度（紧凑） ----

    private var stagesView: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    sectionHeader("chart.bar", "构建进度")
                    if m.running { ProgressView().controlSize(.small) }
                    if let p = overallPercent {
                        Text("\(Int(p))%").font(.system(size: 12, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }
                if m.stages.isEmpty {
                    Text("开始构建后，这里显示脚本自己的每个阶段")
                        .font(.system(size: 12)).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 4)
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(m.stages, id: \.id) { s in
                                HStack(spacing: 8) {
                                    if s.state == .running { ProgressView().controlSize(.mini).frame(width: 14) }
                                    else {
                                        Image(systemName: s.state.icon).font(.system(size: 11))
                                            .foregroundStyle(s.state.color).frame(width: 14)
                                    }
                                    Text(s.name).font(.system(size: 12, design: .monospaced)).lineLimit(1)
                                    if let p = s.percent, s.state == .running {
                                        ProgressView(value: p / 100).frame(width: 70)
                                        Text("\(Int(p))%").font(.system(size: 10.5, design: .monospaced))
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer(minLength: 6)
                                    if !s.detail.isEmpty {
                                        Text(s.detail).font(.system(size: 10.5))
                                            .foregroundStyle(.tertiary).lineLimit(1)
                                    }
                                }
                            }
                        }
                    }
                    .frame(height: 78)
                }
            }.padding(8)
        }
    }

    private var overallPercent: Double? {
        let ps = m.stages.compactMap { $0.state == .done ? 100.0 : ($0.state == .running ? $0.percent : nil) }
        guard !ps.isEmpty else { return nil }
        return ps.reduce(0, +) / Double(ps.count)
    }

    // ---- 日志（紧凑） ----

    private var logView: some View {
        ScrollViewReader { sp in
            ScrollView {
                Text(m.logTail.isEmpty ? "构建日志会显示在这里" : m.logTail)
                    .font(.system(size: 10, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .foregroundStyle(.secondary)
                    .padding(6)
                    .id("end")
            }
            .frame(height: 88)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .textBackgroundColor)))
            .onChange(of: m.logTail) { _ in sp.scrollTo("end", anchor: .bottom) }
        }
    }

    // ---- 底部（固定） ----

    private var footer: some View {
        HStack(spacing: 14) {
            Button(m.running ? "停止" : (m.done ? "重新构建" : "开始构建")) {
                m.running ? m.stop() : m.startBuild()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .font(.system(size: 14, weight: .semibold))
            .disabled(!m.running && !m.canBuild)

            statusText
            Spacer(minLength: 8)
            Button("输出目录…") {
                let d = NSOpenPanel(); d.canChooseDirectories = true; d.canChooseFiles = false
                if d.runModal() == .OK, let u = d.url { m.outDir = u.path }
            }
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 12)
    }

    @ViewBuilder private var statusText: some View {
        if !m.doneNote.isEmpty {
            Text(m.doneNote).font(.system(size: 12))
                .foregroundStyle(m.done ? Color.green : Color.orange).lineLimit(2)
        } else if !m.depsChecked {
            Text("正在检测依赖…").font(.system(size: 12)).foregroundStyle(.secondary)
        } else if !m.allDepsPresent {
            Text("先安装上方缺失的依赖").font(.system(size: 12)).foregroundStyle(.orange)
        } else if !m.repoOK {
            Text("先选择项目仓库").font(.system(size: 12)).foregroundStyle(.orange)
        } else if m.basePath.isEmpty || m.keysPath.isEmpty {
            Text("还需要选择游戏本体和 prod.keys").font(.system(size: 12)).foregroundStyle(.orange)
        } else {
            Text("输出：\(short(m.outDir.isEmpty ? (m.basePath as NSString).deletingLastPathComponent : m.outDir))")
                .font(.system(size: 11.5, design: .monospaced))
                .foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
        }
    }
}
