import SwiftUI

// NS Port Builder: a macOS front end that walks a user through building a playable
// IPA from their own Switch game files. Not part of the host runtime; drives the
// repository's scripts (build_ipa_from_nsp.py, romfs_arc.py) as subprocesses.

struct FileInfo: Identifiable {
    let id = UUID()
    let name: String
    let present: Bool
    var detail: String
}

struct BuildStep: Identifiable {
    let id = UUID()
    let name: String
    var state: StepState = .pending
    var detail: String = ""
}

enum StepState: Equatable {
    case pending, running, done, failed
    var icon: String {
        switch self {
        case .pending: return "○"
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

final class BuildModel: ObservableObject {
    @Published var gameDir: String = ""
    @Published var keysPath: String = ""
    @Published var outDir: String = ""
    @Published var files: [FileInfo] = []
    @Published var steps: [BuildStep] = []
    @Published var running = false
    @Published var logTail = ""
    @Published var done = false
    private var proc: Process?

    static let repo = "/Users/hejie/ZCodeProject/nxnative-romfs-archive"   // TODO: discover relative to the app

    func scanFiles() {
        let dir = gameDir
        guard !dir.isEmpty, FileManager.default.fileExists(atPath: dir) else { files = []; return }
        let nsps = (try? FileManager.default.contentsOfDirectory(atPath: dir))?.filter { $0.lowercased().hasSuffix(".nsp") } ?? []
        let hasBase = nsps.contains { $0.contains("[v0]") }
        let hasUpd = nsps.contains { $0.lowercased().contains("[upd]") }
        let hasKeys = FileManager.default.fileExists(atPath: keysPath)
        var f: [FileInfo] = [
            FileInfo(name: "游戏本体", present: hasBase, detail: hasBase ? (nsps.first { $0.contains("[v0]") } ?? "") : "缺少 [v0] NSP"),
            FileInfo(name: "更新包", present: hasUpd, detail: hasUpd ? (nsps.first { $0.lowercased().contains("[upd]") } ?? "") : "可选，建议提供"),
            FileInfo(name: "主机密钥", present: hasKeys, detail: keysPath),
        ]
        if !hasKeys, !keysPath.isEmpty { f[2].detail = "文件不存在" }
        files = f
    }

    func startBuild() {
        running = true; done = false
        steps = [
            BuildStep(name: "1/5 解包（NSP → ExeFS + RomFS，约 2 分钟）", state: .running),
            BuildStep(name: "2/5 模块改写（指令适配 Apple）", state: .pending),
            BuildStep(name: "3/5 Shader 拆分与编译（约 50 分钟）", state: .pending),
            BuildStep(name: "4/5 打包瘦身 IPA", state: .pending),
            BuildStep(name: "5/5 RomFS 归档分片（到输出目录）", state: .pending),
        ]
        let script = Self.repo + "/scripts/build_ipa_from_nsp.py"
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = [script, gameDir, "-k", keysPath]
        p.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                         "DOTNET_ROOT": NSHomeDirectory() + "/.dotnet", "USER": NSUserName()]
        let pipe = Pipe()
        p.standardOutput = pipe; p.standardError = pipe
        p.terminationHandler = { [weak self] status in
            DispatchQueue.main.async {
                guard let self else { return }
                self.running = false
                if status.terminationStatus == 0 {
                    self.markAllDone()
                    self.done = true
                    self.packArchive()
                } else { self.failLast("退出码 \(status.terminationStatus)——看下方日志末尾") }
            }
        }
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData; guard let s = String(data: d, encoding: .utf8), !s.isEmpty else { return }
            DispatchQueue.main.async { self?.ingest(s) }
        }
        proc = p
        try? p.run()
    }

    private func ingest(_ chunk: String) {
        logTail += chunk
        if logTail.count > 8000 { logTail = String(logTail.suffix(6000)) }
        for (i, st) in steps.enumerated() where st.state == .running {
            if chunk.contains("✓") && chunk.contains("[\(i + 1)/") {
                steps[i].state = .done
                if i + 1 < steps.count { steps[i + 1].state = .running }
            } else if chunk.contains("✗") && chunk.contains("[\(i + 1)/") {
                steps[i].state = .failed
            }
        }
    }
    private func markAllDone() { for i in steps.indices { steps[i].state = .done } }
    private func failLast(_ why: String) {
        if let i = steps.lastIndex(where: { $0.state == .running }) { steps[i].state = .failed; steps[i].detail = why }
        else { steps[steps.count - 1].detail = why }
    }

    // 5/5: the RomFS archive, written next to the build's extract directory
    private func packArchive() {
        let romfs = gameDir + "/0100F2C0115B6000_build/extract/v720896/RomFS"
        guard FileManager.default.fileExists(atPath: romfs) else {
            steps[4].state = .failed; steps[4].detail = "找不到解出的 RomFS（游戏 ID 不同时路径会变）"; return
        }
        let arc = outDir.isEmpty ? gameDir + "/archive" : outDir + "/archive"
        try? FileManager.default.createDirectory(atPath: arc, withIntermediateDirectories: true)
        let script = Self.repo + "/dm/tools/romfs_arc.py"
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = [script, "pack", romfs, arc + "/romfs", "--shard-mib", "200"]
        p.environment = ["PATH": "/usr/bin:/bin", "PYTHONPATH": Self.repo + "/dm/tools"]
        let pipe = Pipe(); p.standardOutput = pipe; p.standardError = pipe
        p.terminationHandler = { [weak self] status in DispatchQueue.main.async {
            guard let self else { return }
            if status.terminationStatus == 0 { self.steps[4].state = .done; self.steps[4].detail = arc }
            else { self.steps[4].state = .failed; self.steps[4].detail = "归档失败（退出码 \(status.terminationStatus)）" }
        }}
        try? p.run()
    }


    // ---- Dependencies (checked at launch; installable one by one) ----
    struct Dep: Identifiable {
        let id = UUID()
        let name: String
        let hint: String
        var present: Bool
        var installing: Bool = false
        let installCmd: [String]   // run via bash; empty = manual (Xcode from the App Store)
    }

    @Published var deps: [Dep] = []
    @Published var depsChecked = false

    nonisolated static func detectDepsSync() -> [Dep] {
        func have(_ tool: String) -> Bool {
            let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/which")
            p.arguments = [tool]
            let pipe = Pipe(); p.standardOutput = pipe; p.standardError = Pipe()
            p.standardInput = FileHandle.nullDevice
            try? p.run(); p.waitUntilExit()
            return p.terminationStatus == 0
        }
        var out: [Dep] = []
        let xcode = FileManager.default.fileExists(atPath: "/Applications/Xcode.app") &&
                    have("xcodebuild")
        out.append(Dep(name: "Xcode + iOS SDK", hint: "App Store 安装，约 12 GB", present: xcode, installCmd: []))
        let mt = have("xcrun") && {
            let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun")
            p.arguments = ["-sdk", "macosx", "metal", "--version"]
            let pipe = Pipe(); p.standardOutput = Pipe(); p.standardError = Pipe()
            p.standardInput = FileHandle.nullDevice
            try? p.run(); p.waitUntilExit()
            return p.terminationStatus == 0
        }()
        out.append(Dep(name: "Metal Toolchain", hint: "xcodebuild -downloadComponent MetalToolchain（约 840 MB）", present: mt,
                       installCmd: ["xcodebuild", "-downloadComponent", "MetalToolchain"]))
        let brew = have("brew")
        out.append(Dep(name: "Homebrew", hint: "brew.sh（后续包的前置）", present: brew,
                       installCmd: ["/bin/bash", "-c",
                         "NONINTERACTIVE=1 /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""]))
        for (pkg, hint) in [("xcodegen", "Xcode 工程生成"), ("zstd", "解压"), ("spirv-cross", "shader 转换")] {
            out.append(Dep(name: "brew: " + pkg, hint: hint, present: brew && have(pkg),
                           installCmd: ["/opt/homebrew/bin/brew", "install", pkg]))
        }
        let dotnet = have("dotnet")
        out.append(Dep(name: ".NET SDK 10", hint: "dotnet-install.sh 装到 ~/.dotnet", present: dotnet,
                       installCmd: ["/bin/bash", "-c",
                         "curl -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/di.sh && chmod +x /tmp/di.sh && /tmp/di.sh --channel 10.0 --install-dir $HOME/.dotnet"]))
        // python packages: importable in the system python3
        let pyok: Bool = {
            let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            p.arguments = ["-c", "import lz4, capstone, fontTools, backports.zstd"]
            let pipe = Pipe(); p.standardOutput = Pipe(); p.standardError = Pipe()
            p.standardInput = FileHandle.nullDevice
            try? p.run(); p.waitUntilExit()
            return p.terminationStatus == 0
        }()
        out.append(Dep(name: "Python 包", hint: "pip install lz4 capstone fonttools backports.zstd", present: pyok,
                       installCmd: ["/usr/bin/python3", "-m", "pip", "install", "--user", "lz4", "capstone", "fonttools", "backports.zstd"]))
        return out
    }

    func checkDeps() {
        DispatchQueue.global().async {
            let d = Self.detectDepsSync()
            DispatchQueue.main.async { self.deps = d; self.depsChecked = true }
        }
    }

    func installDep(_ dep: Dep) {
        guard !dep.installCmd.isEmpty else {
            if let i = deps.firstIndex(where: { $0.id == dep.id }) { deps[i].installing = true }
            NSWorkspace.shared.open(URL(fileURLWithPath: "/Applications/App Store.app"))
            return   // Xcode: the user installs it from the App Store; re-check on return
        }
        guard let i = deps.firstIndex(where: { $0.id == dep.id }) else { return }
        deps[i].installing = true
        let cmd = dep.installCmd
        DispatchQueue.global().async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/bash")
            p.arguments = ["-c"] + [cmd.joined(separator: " ")]
            p.environment = ["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "NONINTERACTIVE": "1"]
            let pipe = Pipe(); p.standardOutput = Pipe(); p.standardError = pipe
            p.standardInput = FileHandle.nullDevice
            try? p.run(); p.waitUntilExit()
            DispatchQueue.main.async {
                if let j = self.deps.firstIndex(where: { $0.id == dep.id }) {
                    self.deps[j].installing = false
                    self.checkDeps()
                }
            }
        }
    }


    var allDepsPresent: Bool { depsChecked && deps.allSatisfy { $0.present } }
    func stop() { proc?.terminate(); running = false }
}

struct ContentView: View {
    @StateObject private var m = BuildModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Image(systemName: "gamecontroller.fill").font(.system(size: 36)).foregroundColor(.green)
                VStack(alignment: .leading) {
                    Text("NS Port Builder").font(.title2.bold())
                    Text("Switch 游戏 → iPhone IPA · 归档分片 · 大内存").font(.caption).foregroundColor(.secondary)
                }
                Spacer()
            }
            GroupBox {
                VStack(alignment: .leading, spacing: 10) {
                    HStack { Text("游戏数据").font(.headline); Spacer()
                        Button("选择…") { pickDir() } }
                    Text(m.gameDir.isEmpty ? "未选择" : m.gameDir).font(.system(.caption, design: .monospaced)).lineLimit(1).truncationMode(.head)
                    ForEach(m.files) { f in
                        HStack {
                            Image(systemName: f.present ? "checkmark.circle.fill" : "xmark.circle").foregroundColor(f.present ? .green : .red)
                            Text(f.name).frame(width: 70, alignment: .leading)
                            Text(f.detail).font(.system(.caption, design: .monospaced)).lineLimit(1).truncationMode(.middle).foregroundColor(.secondary)
                        }
                    }
                }.padding(6)
            }

            GroupBox {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("设备依赖").font(.headline)
                        Spacer()
                        if !m.depsChecked { ProgressView().controlSize(.small); Text("检测中…").font(.caption).foregroundColor(.secondary) }
                        else if m.allDepsPresent { Image(systemName: "checkmark.circle.fill").foregroundColor(.green); Text("全部就绪").font(.caption).foregroundColor(.green) }
                        Button("重新检测") { m.checkDeps() }.controlSize(.small)
                    }
                    ForEach(m.deps) { d in
                        HStack {
                            if d.installing { ProgressView().controlSize(.small) }
                            else { Image(systemName: d.present ? "checkmark.circle.fill" : "xmark.circle").foregroundColor(d.present ? .green : .red) }
                            Text(d.name).frame(width: 150, alignment: .leading)
                            Text(d.hint).font(.caption).foregroundColor(.secondary).lineLimit(1).truncationMode(.tail)
                            Spacer()
                            if !d.present && !d.installing {
                                Button(d.installCmd.isEmpty ? "打开 App Store" : "安装") { m.installDep(d) }.controlSize(.small)
                            } else if d.installing { Text("安装中…").font(.caption).foregroundColor(.orange) }
                        }
                    }
                }.padding(6)
            }

            GroupBox {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(m.steps) { s in
                        HStack {
                            if s.state == .running { ProgressView().controlSize(.small) }
                            else { Image(systemName: s.state.icon).foregroundColor(s.state.color) }
                            Text(s.name).font(.system(.callout, design: .monospaced))
                            Spacer()
                            if !s.detail.isEmpty { Text(s.detail).font(.caption2).foregroundColor(.secondary).lineLimit(1) }
                        }
                    }
                }.padding(6)
            }
            ScrollView {
                Text(m.logTail.isEmpty ? "构建日志会显示在这里" : m.logTail)
                    .font(.system(.caption2, design: .monospaced)).frame(maxWidth: .infinity, alignment: .leading)
                    .foregroundColor(.secondary)
            }.frame(height: 140).background(Color(nsColor: .textBackgroundColor)).cornerRadius(6)
            HStack {
                Button(m.running ? "停止" : (m.done ? "重新构建" : "开始构建")) {
                    m.running ? m.stop() : m.startBuild()
                }
                .buttonStyle(.borderedProminent).disabled(m.gameDir.isEmpty || m.keysPath.isEmpty || !m.allDepsPresent)
                if !m.allDepsPresent { Text("先安装上方缺失的依赖").foregroundColor(.orange) }
                else if m.done { Text("完成：IPA 与归档已生成").foregroundColor(.green) }
                Spacer()
            }
        }.padding(20).frame(width: 640, height: 680)
        .onAppear { m.keysPath = NSHomeDirectory() + "/keys/prod.keys"; m.scanFiles(); m.checkDeps() }
        .onChange(of: m.gameDir) { _ in m.scanFiles() }
    }
    func pickDir() {
        let d = NSOpenPanel(); d.canChooseDirectories = true; d.canChooseFiles = false
        if d.runModal() == .OK, let u = d.url { m.gameDir = u.path
            if m.keysPath.isEmpty || !FileManager.default.fileExists(atPath: m.keysPath),
               let k = (try? FileManager.default.contentsOfDirectory(atPath: u.path))?.first(where: { $0 == "prod.keys" }) {
                m.keysPath = u.path + "/" + k
            }
        }
    }
}
