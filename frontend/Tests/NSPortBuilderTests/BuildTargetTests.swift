import XCTest
@testable import NSPortBuilder

final class BuildTargetTests: XCTestCase {
    func testMacAppNeverLandsInTemporaryInputStaging() {
        XCTAssertEqual(BuildTarget.macApp.outputPath(directory: "", baseDirectory: "/Volumes/Games/My Game", titleID: "0100"),
                       "/Volumes/Games/My Game/0100.app")
        XCTAssertEqual(BuildTarget.macApp.outputPath(directory: "/Volumes/Output", baseDirectory: "/Volumes/Games", titleID: "0100"),
                       "/Volumes/Output/0100.app")
    }

    func testIOSKeepsDefaultNamingUnlessOutputOverridden() {
        XCTAssertNil(BuildTarget.ios.outputPath(directory: "", baseDirectory: "/Volumes/Games", titleID: "0100"))
        XCTAssertEqual(BuildTarget.ios.outputPath(directory: "/Volumes/Output", baseDirectory: "/Volumes/Games", titleID: "0100"),
                       "/Volumes/Output/0100.ipa")
    }

    func testTargetSwitchChangesSDKAndProjectRequirements() {
        let deps = ["xcode", "xcodeMac", "brew:xcodegen", "metal", "python", "dotnet"]
        XCTAssertEqual(deps.filter { BuildTarget.macApp.requires(dependency: $0) }, ["xcodeMac", "metal", "python", "dotnet"])
        XCTAssertEqual(deps.filter { BuildTarget.ios.requires(dependency: $0) }, ["xcode", "brew:xcodegen", "metal", "python", "dotnet"])
    }

    func testIPAOutputHandlesUpstreamTimestampAndSpaces() {
        XCTAssertEqual(BuildTarget.ipaPath(from: "[12:34:56] output IPA: /Volumes/My Games/Game.ipa"), "/Volumes/My Games/Game.ipa")
        XCTAssertNil(BuildTarget.ipaPath(from: "[12:34:56] Mac app: building"))
    }
}
