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
                .buttonStyle(.borderedProminent).disabled(m.gameDir.isEmpty || m.keysPath.isEmpty)
                if m.done { Text("完成：IPA 与归档已生成").foregroundColor(.green) }
                Spacer()
            }
        }.padding(20).frame(width: 640, height: 680)
        .onAppear { m.keysPath = NSHomeDirectory() + "/keys/prod.keys"; m.scanFiles() }
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
