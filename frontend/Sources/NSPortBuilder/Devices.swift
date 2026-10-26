import Foundation

/// An iPhone or iPad paired with this Mac (Xcode's `devicectl`), a target for installing a build directly.
struct AppleDevice: Identifiable, Equatable {
    let id: String          // the UDID
    let name: String
    let model: String
    let os: String
    let reachable: Bool     // connected now, by cable or the local network
}

/// A development signing identity in the keychain and the team it signs for.
struct SigningTeam: Identifiable, Equatable {
    let id: String          // the team ID: the certificate's organizational unit, not the code in its name
    let identity: String    // "Apple Development: Name (ABCDE12345)"
}

/// Xcode's own tools for devices and signing: `xcrun devicectl` and `security`. Nothing here signs or installs;
/// it only reads what is paired and what can sign.
enum DeviceTools {
    /// The paired physical iPhones and iPads, reachable ones first.
    static func devices(xcrun: String = "/usr/bin/xcrun") -> [AppleDevice] {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("nxnative-devices-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: file) }
        guard run(xcrun, ["devicectl", "list", "devices", "--json-output", file.path]) != nil,
              let data = try? Data(contentsOf: file) else { return [] }
        return parseDevices(data)
    }

    static func parseDevices(_ data: Data) -> [AppleDevice] {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let result = root["result"] as? [String: Any], let list = result["devices"] as? [[String: Any]] else { return [] }
        let devices: [AppleDevice] = list.compactMap { d in
            let hardware = d["hardwareProperties"] as? [String: Any] ?? [:]
            let properties = d["deviceProperties"] as? [String: Any] ?? [:]
            let connection = d["connectionProperties"] as? [String: Any] ?? [:]
            guard hardware["reality"] as? String == "physical", hardware["platform"] as? String == "iOS",
                  connection["pairingState"] as? String == "paired",
                  let udid = hardware["udid"] as? String, !udid.isEmpty else { return nil }
            return AppleDevice(id: udid, name: properties["name"] as? String ?? udid,
                               model: hardware["marketingName"] as? String ?? "",
                               os: properties["osVersionNumber"] as? String ?? "",
                               reachable: connection["transportType"] is String)
        }
        return devices.sorted { ($0.reachable ? 0 : 1, $0.name) < ($1.reachable ? 0 : 1, $1.name) }
    }

    /// The development identities that can sign for a device, with their teams.
    static func teams() -> [SigningTeam] {
        guard let list = run("/usr/bin/security", ["find-identity", "-v", "-p", "codesigning"]) else { return [] }
        var seen = Set<String>()
        return identities(list).compactMap { identity in
            guard let pem = run("/usr/bin/security", ["find-certificate", "-c", identity, "-p"]),
                  let subject = run("/usr/bin/openssl", ["x509", "-noout", "-subject"], input: pem),
                  let team = team(fromSubject: subject), seen.insert(team + identity).inserted else { return nil }
            return SigningTeam(id: team, identity: identity)
        }
    }

    /// The quoted names of `security find-identity` that sign for devices (development, not distribution).
    static func identities(_ text: String) -> [String] {
        text.split(separator: "\n").compactMap { line in
            guard let open = line.firstIndex(of: "\""), let close = line.lastIndex(of: "\""), open < close else { return nil }
            let name = String(line[line.index(after: open)..<close])
            return name.hasPrefix("Apple Development:") || name.hasPrefix("iPhone Developer:") ? name : nil
        }
    }

    /// OU= of a certificate subject, as `openssl x509 -subject` prints it.
    static func team(fromSubject subject: String) -> String? {
        guard let range = subject.range(of: #"OU\s*=\s*([A-Z0-9]{10})"#, options: .regularExpression) else { return nil }
        return subject[range].split(separator: "=").last.map { $0.trimmingCharacters(in: .whitespaces) }
    }

    private static func run(_ tool: String, _ args: [String], input: String? = nil) -> String? {
        let p = Process(), out = Pipe(), inPipe = Pipe()
        p.executableURL = URL(fileURLWithPath: tool)
        p.arguments = args
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        p.standardInput = input == nil ? FileHandle.nullDevice : inPipe
        do { try p.run() } catch { return nil }
        if let input { inPipe.fileHandleForWriting.write(Data(input.utf8)); try? inPipe.fileHandleForWriting.close() }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return p.terminationStatus == 0 ? String(decoding: data, as: UTF8.self) : nil
    }
}
