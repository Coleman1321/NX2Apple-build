import AppKit
import SwiftUI

/// Only paths and presentation metadata live here. Game data stays on its original drive.
struct LibraryGame: Codable, Identifiable, Equatable {
    var id: UUID = UUID()
    var titleID: String
    var name: String
    var appPath = ""
    var ipaPath = ""
    var archivePath = ""
    var lastTarget = "ios"
    var inputs: [String: [String]] = [:]
    var outputDirectory = ""
    var artworkPath = ""
    var launchOptions: [String: String] = [:]
    var iosAppPath = ""
    var installedDevice = ""

    var isReady: Bool {
        guard let app = try? MacGameBundle.read(URL(fileURLWithPath: appPath)) else { return false }
        return app.titleID == titleID
    }

    /// Signed and installed on a paired device (installedDevice is its UDID): Play starts it there.
    var onDevice: Bool { !installedDevice.isEmpty && FileManager.default.fileExists(atPath: iosAppPath + "/Info.plist") }

    var hasIOSBuild: Bool {
        (!ipaPath.isEmpty && FileManager.default.fileExists(atPath: ipaPath)) ||
        (!iosAppPath.isEmpty && FileManager.default.fileExists(atPath: iosAppPath + "/Info.plist"))
    }
}

extension LibraryGame {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        titleID = try c.decode(String.self, forKey: .titleID)
        name = try c.decode(String.self, forKey: .name)
        appPath = try c.decodeIfPresent(String.self, forKey: .appPath) ?? ""
        ipaPath = try c.decodeIfPresent(String.self, forKey: .ipaPath) ?? ""
        archivePath = try c.decodeIfPresent(String.self, forKey: .archivePath) ?? ""
        lastTarget = try c.decodeIfPresent(String.self, forKey: .lastTarget) ?? "ios"
        inputs = try c.decodeIfPresent([String: [String]].self, forKey: .inputs) ?? [:]
        outputDirectory = try c.decodeIfPresent(String.self, forKey: .outputDirectory) ?? ""
        artworkPath = try c.decodeIfPresent(String.self, forKey: .artworkPath) ?? ""
        launchOptions = try c.decodeIfPresent([String: String].self, forKey: .launchOptions) ?? [:]
        iosAppPath = try c.decodeIfPresent(String.self, forKey: .iosAppPath) ?? ""
        installedDevice = try c.decodeIfPresent(String.self, forKey: .installedDevice) ?? ""
    }
}

/// One row of the app's `dm/launcher.json` (dm/games/settings.py), the list the iPhone launcher shows
/// (dm/ios/Sources/LauncherSettings.swift). Each sets an environment variable the game reads at start.
struct LaunchSetting: Decodable, Identifiable {
    let env, kind, label, note, def: String
    let section: String?
    let options: [[String]]?   // choice: [value, label]
    let min, max, step: Double?   // range
    let on, off: String?   // toggle: the values the variable takes
    var id: String { env }
    var sectionTitle: String { section ?? "Game" }
    var onValue: String { on ?? "1" }
    var offValue: String { off ?? "0" }
    func isDefault(_ v: String) -> Bool {   // a range compares as numbers (a slider writes 1.00 for 1.0)
        kind == "range" ? abs((Double(v) ?? .nan) - (Double(def) ?? .nan)) < 1e-6 : v == def
    }
    func accepts(_ v: String) -> Bool {   // a saved choice the build still offers
        switch kind {
        case "choice": return options?.contains { $0.first == v } ?? false
        case "range":
            guard let n = Double(v), n.isFinite, let lo = min, let hi = max else { return false }
            return n >= lo && n <= hi
        case "toggle": return v == onValue || v == offValue
        default: return true
        }
    }
    enum CodingKeys: String, CodingKey { case env, kind, label, note, def = "default", section, options, min, max, step, on, off }

    private struct File: Decodable { let settings: [LaunchSetting] }
    /// The settings a Mac app was packed with; nil for an app packed before they were.
    static func read(app: String) -> [LaunchSetting]? {
        let url = URL(fileURLWithPath: app).appendingPathComponent("Contents/Resources/dm/launcher.json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return (try? JSONDecoder().decode(File.self, from: data))?.settings
    }
}

extension LibraryGame {
    /// The value each setting takes: the player's choice while the build still offers it, else the game's default.
    func launchValue(_ s: LaunchSetting) -> String {
        launchOptions[s.env].flatMap { s.accepts($0) ? $0 : nil } ?? s.def
    }

    /// Every setting goes into the app's environment, as the iPhone launcher sets them before the game starts.
    func launchEnvironment(_ settings: [LaunchSetting]) -> [String: String] {
        Dictionary(uniqueKeysWithValues: settings.map { ($0.env, launchValue($0)) })
    }
}

struct MacGameBundle {
    let titleID: String
    let name: String

    enum Invalid: LocalizedError {
        case notGame
        var errorDescription: String? { "Choose a complete nxnative Mac game app built by the NSP pipeline." }
    }

    static func read(_ url: URL) throws -> MacGameBundle {
        guard url.pathExtension.lowercased() == "app",
              let data = try? Data(contentsOf: url.appendingPathComponent("Contents/Info.plist")),
              let info = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              let rawID = info["DMTitleID"] as? String,
              rawID.range(of: "^[0-9A-Fa-f]{16}$", options: .regularExpression) != nil,
              let executable = info["CFBundleExecutable"] as? String,
              !executable.isEmpty, executable != ".", executable != "..", !executable.contains("/"),
              FileManager.default.isExecutableFile(atPath: url.appendingPathComponent("Contents/MacOS/" + executable).path),
              FileManager.default.isExecutableFile(atPath: url.appendingPathComponent("Contents/MacOS/dmhost").path)
        else { throw Invalid.notGame }
        return MacGameBundle(titleID: rawID.uppercased(),
                             name: info["CFBundleDisplayName"] as? String ?? info["CFBundleName"] as? String ?? url.deletingPathExtension().lastPathComponent)
    }
}

final class GameLibrary: ObservableObject {
    @Published private(set) var games: [LibraryGame] = []
    @Published var selectedID: UUID?
    @Published var error: String?
    @Published private(set) var folder = ""
    @Published private(set) var scanning = false
    private let file: URL
    private struct Snapshot: Codable {
        let games: [LibraryGame]
        let folder: String
    }

    init(file: URL? = nil) {
        self.file = file ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("NS Port Builder/library.json")
        if FileManager.default.fileExists(atPath: self.file.path) {
            do {
                let data = try Data(contentsOf: self.file)
                if let snapshot = try? JSONDecoder().decode(Snapshot.self, from: data) {
                    games = snapshot.games
                    folder = snapshot.folder
                } else { games = try JSONDecoder().decode([LibraryGame].self, from: data) }
            }
            catch { self.error = error.localizedDescription }
        }
        selectedID = games.first?.id
    }

    var selected: LibraryGame? { games.first { $0.id == selectedID } }

    func save() {
        do {
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(Snapshot(games: games, folder: folder)).write(to: file, options: .atomic)
        } catch { self.error = error.localizedDescription }
    }

    func setFolder(_ url: URL) {
        folder = url.standardizedFileURL.path
        save()
        discover()
    }

    /// A bounded scan of build locations, never of a game's multi-GB contents.
    static func builtApps(in root: URL) -> [URL] {
        let fm = FileManager.default
        guard let enumerator = fm.enumerator(at: root, includingPropertiesForKeys: [.isDirectoryKey, .contentModificationDateKey],
                                             options: [.skipsHiddenFiles], errorHandler: { _, _ in true }) else { return [] }
        let ignored = Set(["romfs", "extract", "node_modules", "xcode", "archive", "tools", "firmware", "keys", "venv", "shader", "msl", "pso", "bench", "harness", "runs"])
        var apps: [URL] = []
        var visited = 0
        while let url = enumerator.nextObject() as? URL {
            guard (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true else { continue }
            visited += 1
            if visited > 4000 { break }
            if url.pathExtension.lowercased() == "app" {
                enumerator.skipDescendants()
                if (try? MacGameBundle.read(url)) != nil { apps.append(url) }
            } else if enumerator.level >= 4 || ignored.contains(url.lastPathComponent.lowercased()) || url.lastPathComponent.hasSuffix("_build") || url.lastPathComponent.hasSuffix("_survey") || url.lastPathComponent.hasSuffix("-work") {
                enumerator.skipDescendants()
            }
        }
        return apps.sorted {
            let left = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let right = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return left == right ? $0.path < $1.path : left > right
        }
    }

    static func sourceGames(in root: URL, repo: String) -> [LibraryGame] {
        guard let e = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.isDirectoryKey], options: [.skipsHiddenFiles], errorHandler: { _, _ in true }) else { return [] }
        var result: [String: LibraryGame] = [:]
        while let url = e.nextObject() as? URL {
            if (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true {
                let name = url.lastPathComponent.lowercased()
                if e.level >= 4 || name.hasSuffix(".app") || name.hasSuffix("_build") || name.hasSuffix("-work") || name.hasSuffix("_survey") || ["romfs", "extract", "tools", "venv", "archive", "harness", "runs", "shader", "node_modules"].contains(name) { e.skipDescendants() }
                continue
            }
            guard ["nsp", "xci", "nsz", "xcz"].contains(url.pathExtension.lowercased()),
                  let id = BuildModel.titleID(url.lastPathComponent), id & 0xfff == 0 else { continue }
            let tid = String(format: "%016llX", id)
            guard result[tid] == nil else { continue }
            var game = LibraryGame(titleID: tid, name: title(for: url.path, repo: repo, titleID: tid))
            let parent = url.deletingLastPathComponent()
            let files = (try? FileManager.default.contentsOfDirectory(at: parent, includingPropertiesForKeys: nil)) ?? []
            game.inputs["base"] = [url.path]
            game.inputs["update"] = files.filter { BuildModel.titleID($0.lastPathComponent) == id + 0x800 && ["nsp", "xci", "nsz", "xcz"].contains($0.pathExtension.lowercased()) }
                .sorted { BuildModel.updateVersion($0.lastPathComponent) > BuildModel.updateVersion($1.lastPathComponent) }.prefix(1).map(\.path)
            game.inputs["dlc"] = files.filter {
                guard let other = BuildModel.titleID($0.lastPathComponent) else { return false }
                return other >= id + 0x1000 && other < id + 0x2000 && ["nsp", "nsz"].contains($0.pathExtension.lowercased())
            }.map(\.path)
            game.inputs["keys"] = [parent.appendingPathComponent("prod.keys"), root.appendingPathComponent("keys/prod.keys"), root.appendingPathComponent("prod.keys")]
                .filter { FileManager.default.fileExists(atPath: $0.path) }.prefix(1).map(\.path)
            game.outputDirectory = parent.path
            if let ipa = files.first(where: { $0.pathExtension.lowercased() == "ipa" }) { game.ipaPath = ipa.path }
            result[tid] = game
        }
        return result.values.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }

    func discover(repo: String = BuildModel.findRepo()) {
        guard !folder.isEmpty, !scanning else { return }
        scanning = true
        let root = URL(fileURLWithPath: folder)
        DispatchQueue.global(qos: .utility).async {
            let apps = Self.builtApps(in: root)
            let sources = Self.sourceGames(in: root, repo: repo)
            DispatchQueue.main.async {
                let previousSelection = self.selectedID
                for source in sources {
                    if var existing = self.games.first(where: { $0.titleID == source.titleID }) {
                        if existing.inputs["base", default: []].isEmpty { existing.inputs = source.inputs }
                        if existing.ipaPath.isEmpty { existing.ipaPath = source.ipaPath }
                        self.upsert(existing)
                    } else { self.upsert(source) }
                }
                for url in apps {
                    guard let info = try? MacGameBundle.read(url) else { continue }
                    if let existing = self.games.first(where: { $0.titleID == info.titleID }), existing.isReady { continue }
                    _ = try? self.addApp(url)
                }
                self.selectedID = previousSelection ?? self.games.first?.id
                self.scanning = false
            }
        }
    }

    @discardableResult func addApp(_ url: URL) throws -> UUID {
        let app = try MacGameBundle.read(url)
        var game = games.first { $0.titleID == app.titleID } ?? LibraryGame(titleID: app.titleID, name: app.name)
        game.name = app.name
        game.appPath = url.standardizedFileURL.path
        upsert(game)
        selectedID = game.id
        return game.id
    }

    @discardableResult func rememberInputs(_ model: BuildModel) -> UUID? {
        guard !model.basePath.isEmpty else { return nil }
        let titleID = BuildModel.titleID(model.basePath).map { String(format: "%016llX", $0) }
            ?? URL(fileURLWithPath: model.basePath).standardizedFileURL.path
        var game = games.first { $0.titleID == titleID } ?? LibraryGame(titleID: titleID, name: Self.title(for: model.basePath, repo: model.repoPath, titleID: titleID))
        game.inputs = Dictionary(uniqueKeysWithValues: model.slots.map { ($0.id, $0.paths) })
        game.outputDirectory = model.outDir
        game.lastTarget = model.target
        // An existing output is linked only after validating its metadata and executables.
        let dir = model.outDir.isEmpty ? URL(fileURLWithPath: model.basePath).deletingLastPathComponent().path : model.outDir
        let expected = URL(fileURLWithPath: dir).appendingPathComponent(titleID + ".app")
        if let app = try? MacGameBundle.read(expected), app.titleID == titleID { game.appPath = expected.path }
        upsert(game)
        selectedID = game.id
        return game.id
    }

    func recordCompletedApp(path: String, for id: UUID) {
        guard var game = games.first(where: { $0.id == id }),
              let app = try? MacGameBundle.read(URL(fileURLWithPath: path)),
              app.titleID == game.titleID || game.titleID.hasPrefix("/") else { return }
        game.titleID = app.titleID
        game.appPath = path
        game.name = app.name
        upsert(game)
    }

    func recordCompletedIOS(ipa: String, archive: String, app: String = "", device: String = "", for id: UUID) {
        guard var game = games.first(where: { $0.id == id }),
              FileManager.default.fileExists(atPath: ipa) || FileManager.default.fileExists(atPath: app + "/Info.plist") else { return }
        // What this build made; an earlier build's IPA or installed app stays when this one made none
        if !ipa.isEmpty { game.ipaPath = ipa }
        if !archive.isEmpty { game.archivePath = archive }
        if !app.isEmpty { game.iosAppPath = app; game.installedDevice = device }
        upsert(game)
    }

    /// Only a choice that differs from the game's default is kept, so a setting left at its default follows a later build's.
    func setLaunchOption(_ setting: LaunchSetting, _ value: String, for id: UUID) {
        guard var game = games.first(where: { $0.id == id }) else { return }
        game.launchOptions[setting.env] = setting.isDefault(value) ? nil : value
        upsert(game)
    }

    func resetLaunchOptions(for id: UUID) {
        guard var game = games.first(where: { $0.id == id }) else { return }
        game.launchOptions = [:]
        upsert(game)
    }

    func setArtwork(_ path: String, for id: UUID) {
        guard var game = games.first(where: { $0.id == id }) else { return }
        game.artworkPath = path
        upsert(game)
    }

    func remove(_ id: UUID) {
        games.removeAll { $0.id == id }
        if selectedID == id { selectedID = games.first?.id }
        save()
    }

    private func upsert(_ game: LibraryGame) {
        if let index = games.firstIndex(where: { $0.id == game.id }) { games[index] = game }
        else { games.append(game) }
        save()
    }

    static func title(for path: String, repo: String, titleID: String) -> String {
        if let text = try? String(contentsOfFile: repo + "/dm/games/" + titleID + "/game.tsv", encoding: .utf8),
           let row = text.split(separator: "\n").first(where: { $0.hasPrefix("name\t") }) {
            return String(row.dropFirst(5))
        }
        let filename = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
        let name = filename.replacingOccurrences(of: "\\[[^\\]]*\\]", with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty ? filename : name
    }

    /// Prefer a user's own image, then the game's eShop key art (ArtworkStore), then an existing repository
    /// gameplay screenshot, then the app icon.
    static func artwork(for game: LibraryGame, repo: String, banners: URL = ArtworkStore.shared.directory) -> NSImage? {
        if !game.artworkPath.isEmpty, let image = NSImage(contentsOfFile: game.artworkPath) { return image }
        if let url = ArtworkStore.cachedBanner(game.titleID, in: banners), let image = NSImage(contentsOf: url) { return image }
        func normalized(_ s: String) -> String {
            s.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: Locale(identifier: "en_US_POSIX"))
                .filter { $0.isLetter || $0.isNumber }
        }
        let name = normalized(game.name)
        let images = URL(fileURLWithPath: repo).appendingPathComponent("docs/images")
        let files = (try? FileManager.default.contentsOfDirectory(at: images, includingPropertiesForKeys: nil)) ?? []
        let matches = files.filter {
            ["jpg", "jpeg", "png", "webp"].contains($0.pathExtension.lowercased()) && name.hasSuffix(normalized($0.deletingPathExtension().lastPathComponent))
        }.sorted { $0.lastPathComponent.count > $1.lastPathComponent.count }
        if let url = matches.first, let image = NSImage(contentsOf: url) { return image }
        if !game.appPath.isEmpty, let icon = NSImage(contentsOfFile: game.appPath + "/Contents/Resources/AppIcon.icns") { return icon }
        // Extraction icons are small; they are a fallback, never presented as high-resolution artwork.
        return nil
    }
}
