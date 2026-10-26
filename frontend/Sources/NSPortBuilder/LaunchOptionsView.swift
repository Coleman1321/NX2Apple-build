import SwiftUI

/// A game's launch options: the settings its Mac app was packed with (dm/launcher.json), drawn as the
/// iPhone launcher draws them, one screen grouped by section. Play passes them to the app as its environment.
struct LaunchOptionsView: View {
    @ObservedObject var m: BuildModel
    @ObservedObject var library: GameLibrary
    let gameID: UUID
    @Environment(\.dismiss) private var dismiss

    private var game: LibraryGame? { library.games.first { $0.id == gameID } }
    private var settings: [LaunchSetting]? { game.flatMap { LaunchSetting.read(app: $0.appPath) } }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(m.t("launch.title")).font(.manrope(26, .heavy)).tracking(-0.6)
                    if let game { Text(game.name).font(.manrope(14)).foregroundStyle(.secondary) }
                }
                Spacer()
            }
            .padding(.horizontal, 30).padding(.top, 28).padding(.bottom, 20)
            if let settings, !settings.isEmpty, let game {
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        ForEach(sections(settings), id: \.self) { section in
                            let rows = settings.filter { $0.sectionTitle == section }
                            VStack(alignment: .leading, spacing: 10) {
                                Text(m.t("launch.section." + section)).font(.manrope(15, .semibold)).foregroundStyle(.secondary)
                                    .padding(.leading, 2)
                                VStack(spacing: 0) {
                                    ForEach(rows) { s in
                                        row(s, game)
                                        if s.id != rows.last?.id { Divider().opacity(0.25).padding(.leading, 18) }
                                    }
                                }
                                .background(LauncherPalette.surface.opacity(0.75), in: RoundedRectangle(cornerRadius: 14))
                                .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Color.white.opacity(0.06)))
                            }
                        }
                    }
                    .padding(.horizontal, 30).padding(.bottom, 24)
                }
            } else {
                Text(m.t("launch.none")).font(.manrope(14)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(30).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            Divider().opacity(0.3)
            HStack(spacing: 14) {
                Text(m.t("launch.applied")).font(.manrope(12)).foregroundStyle(.secondary).lineLimit(2)
                Spacer(minLength: 8)
                if let game, !game.launchOptions.isEmpty {
                    Button(m.t("launch.reset")) { library.resetLaunchOptions(for: gameID) }
                        .buttonStyle(LauncherSecondaryButtonStyle())
                }
                Button { dismiss() } label: {
                    Text(m.t("launch.done")).font(.manrope(13.5, .bold)).foregroundStyle(.black)
                        .padding(.horizontal, 22).padding(.vertical, 9)
                        .background(LauncherPalette.cream, in: Capsule())
                }
                .buttonStyle(.plain).keyboardShortcut(.defaultAction)
            }
            .padding(.horizontal, 30).padding(.vertical, 16)
        }
        .frame(width: 600, height: 700)
        .background(LauncherPalette.background)
        .font(.manrope(13))
        .preferredColorScheme(.dark)
        .tint(LauncherPalette.cream)
    }

    private func sections(_ settings: [LaunchSetting]) -> [String] {
        settings.reduce(into: []) { if !$0.contains($1.sectionTitle) { $0.append($1.sectionTitle) } }
    }

    private func set(_ s: LaunchSetting, _ value: String) { library.setLaunchOption(s, value, for: gameID) }

    @ViewBuilder private func row(_ s: LaunchSetting, _ game: LibraryGame) -> some View {
        let value = game.launchValue(s)
        HStack(alignment: .center, spacing: 16) {
            VStack(alignment: .leading, spacing: 3) {
                Text(s.label).font(.manrope(14, .medium))
                if !s.note.isEmpty {
                    Text(s.note).font(.manrope(12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 12)
            switch s.kind {
            case "choice":
                let options = (s.options ?? []).map { (value: $0[0], label: $0.count > 1 ? $0[1] : $0[0]) }
                if options.count <= 3 {
                    LauncherSegmented(options: options, selection: value) { set(s, $0) }
                } else {
                    LauncherMenuPicker(options: options, selection: value) { set(s, $0) }
                }
            case "range":
                let lo = s.min ?? 0, hi = s.max ?? 1
                LauncherSlider(value: Double(value) ?? Double(s.def) ?? lo, range: lo...hi, step: s.step ?? 0.05) {
                    set(s, String(format: "%.2f", $0))
                }
                .frame(width: 170)
                Text("\(Int(((Double(value) ?? 0) * 100).rounded()))%")
                    .font(.manrope(13, .semibold)).monospacedDigit().foregroundStyle(.secondary)
                    .frame(width: 44, alignment: .trailing)
            default:
                Toggle("", isOn: Binding(get: { value == s.onValue }, set: { set(s, $0 ? s.onValue : s.offValue) }))
                    .labelsHidden().toggleStyle(LauncherSwitchStyle())
            }
        }
        .padding(.horizontal, 18).padding(.vertical, 13)
        .frame(minHeight: 52)
    }
}
