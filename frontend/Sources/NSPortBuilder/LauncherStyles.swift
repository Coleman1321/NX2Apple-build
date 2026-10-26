import SwiftUI

struct LauncherWindowChrome: NSViewRepresentable {
    final class ChromeView: NSView {
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            guard let window else { return }
            window.titleVisibility = .hidden
            window.titlebarAppearsTransparent = true
            window.styleMask.insert(.fullSizeContentView)
            window.backgroundColor = NSColor(red: 0.055, green: 0.055, blue: 0.06, alpha: 1)
            window.isMovableByWindowBackground = true
        }
    }
    func makeNSView(context: Context) -> NSView { ChromeView() }
    func updateNSView(_ nsView: NSView, context: Context) {}
}

struct LauncherSecondaryButtonStyle: ButtonStyle {
    /// Text and border in this colour (the build bar's Stop); plain white otherwise.
    var accent: Color? = nil
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.manrope(13, .semibold))
            .padding(.horizontal, 15).padding(.vertical, 9)
            .background(Color.white.opacity(configuration.isPressed ? 0.13 : 0.055), in: RoundedRectangle(cornerRadius: 9))
            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(accent?.opacity(0.75) ?? Color.white.opacity(0.10)))
            .foregroundStyle(enabled ? (accent ?? Color.white.opacity(0.92)) : .gray)
            .opacity(enabled ? 1 : 0.55)
            .contentShape(RoundedRectangle(cornerRadius: 9))
    }
}

/// The launcher's switch: a cream track when on, a dim one when off.
struct LauncherSwitchStyle: ToggleStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        Button { withAnimation(.spring(response: 0.25, dampingFraction: 0.8)) { configuration.isOn.toggle() } } label: {
            ZStack(alignment: configuration.isOn ? .trailing : .leading) {
                Capsule().fill(configuration.isOn ? LauncherPalette.cream : Color.white.opacity(0.14))
                Circle().fill(configuration.isOn ? LauncherPalette.background : Color.white.opacity(0.85))
                    .padding(3)
                    .shadow(color: .black.opacity(0.3), radius: 2, y: 1)
            }
            .frame(width: 40, height: 24)
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .opacity(enabled ? 1 : 0.45)
        .accessibilityAddTraits(configuration.isOn ? .isSelected : [])
    }
}

/// Two or three choices side by side; the chosen one is a cream pill.
struct LauncherSegmented: View {
    let options: [(value: String, label: String)]
    let selection: String
    let choose: (String) -> Void
    var body: some View {
        HStack(spacing: 2) {
            ForEach(options, id: \.value) { o in
                let on = o.value == selection
                Button { withAnimation(.easeOut(duration: 0.15)) { choose(o.value) } } label: {
                    Text(o.label).font(.manrope(12.5, on ? .bold : .medium))
                        .foregroundStyle(on ? Color.black : Color.white.opacity(0.75))
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .background(on ? LauncherPalette.cream : .clear, in: Capsule())
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(3)
        .background(Color.white.opacity(0.06), in: Capsule())
        .overlay(Capsule().strokeBorder(Color.white.opacity(0.08)))
    }
}

/// A longer list of choices: a pill with the current one that opens the list.
struct LauncherMenuPicker: View {
    let options: [(value: String, label: String)]
    let selection: String
    let choose: (String) -> Void
    @State private var open = false
    var body: some View {
        Button { open.toggle() } label: {
            HStack(spacing: 8) {
                Text(options.first { $0.value == selection }?.label ?? selection).font(.manrope(12.5, .semibold))
                Image(systemName: "chevron.down").font(.system(size: 9, weight: .bold)).foregroundStyle(.secondary)
            }
            .padding(.horizontal, 14).padding(.vertical, 7)
            .background(Color.white.opacity(0.06), in: Capsule())
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.10)))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .popover(isPresented: $open, arrowEdge: .bottom) {
            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(options, id: \.value) { o in
                        Button { choose(o.value); open = false } label: {
                            HStack {
                                Text(o.label).font(.manrope(13, o.value == selection ? .bold : .regular))
                                Spacer(minLength: 16)
                                if o.value == selection { Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)).foregroundStyle(LauncherPalette.cream) }
                            }
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .background(o.value == selection ? Color.white.opacity(0.07) : .clear, in: RoundedRectangle(cornerRadius: 7))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(6)
            }
            .frame(width: 240, height: min(CGFloat(options.count) * 33 + 12, 320))
            .preferredColorScheme(.dark)
        }
    }
}

/// A slider without tick marks: a thin track, a cream fill and a round knob; snaps to its step.
struct LauncherSlider: View {
    let value: Double
    let range: ClosedRange<Double>
    let step: Double
    let change: (Double) -> Void
    var body: some View {
        GeometryReader { g in
            let span = range.upperBound - range.lowerBound
            let fraction = span > 0 ? (min(max(value, range.lowerBound), range.upperBound) - range.lowerBound) / span : 0
            let knob: CGFloat = 16, track = g.size.width - knob
            ZStack(alignment: .leading) {
                Capsule().fill(Color.white.opacity(0.14)).frame(height: 4).padding(.horizontal, knob / 2)
                Capsule().fill(LauncherPalette.cream).frame(width: track * fraction + knob / 2, height: 4).padding(.leading, knob / 2)
                Circle().fill(LauncherPalette.cream).frame(width: knob, height: knob)
                    .shadow(color: .black.opacity(0.35), radius: 3, y: 1)
                    .offset(x: track * fraction)
            }
            .frame(maxHeight: .infinity)
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { drag in
                let raw = range.lowerBound + Double(min(max(drag.location.x - knob / 2, 0), track) / max(track, 1)) * span
                let snapped = step > 0 ? (raw / step).rounded() * step : raw
                change(min(max(snapped, range.lowerBound), range.upperBound))
            })
        }
        .frame(height: 22)
    }
}
