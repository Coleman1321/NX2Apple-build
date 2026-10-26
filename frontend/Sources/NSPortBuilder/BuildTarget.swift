import Foundation

/// Player-facing outputs; upstream's `mac` target is a development build, not an app.
enum BuildTarget: String {
    case ios
    case macApp = "mac-app"

    func outputPath(directory: String, baseDirectory: String, titleID: String) -> String? {
        // Always place a Mac app outside temporary input staging, even without an output override.
        guard self == .macApp || !directory.isEmpty else { return nil }
        return URL(fileURLWithPath: directory.isEmpty ? baseDirectory : directory)
            .appendingPathComponent(titleID + (self == .macApp ? ".app" : ".ipa")).path
    }

    func requires(dependency: String) -> Bool {
        if self == .macApp { return dependency != "xcode" && dependency != "brew:xcodegen" }
        return dependency != "xcodeMac"
    }

    static func ipaPath(from line: String) -> String? {
        // Upstream prefixes console messages with a timestamp.
        guard let marker = line.range(of: "output IPA: ") else { return nil }
        return String(line[marker.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
