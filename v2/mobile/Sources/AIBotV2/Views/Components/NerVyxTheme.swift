import SwiftUI

// MARK: - NerVyx Design System
// Midnight Neural theme — mirrors dashboard.wajidali.us brand tokens.

enum NerVyx {

    // MARK: Backgrounds
    static let bg            = Color(hex: "070A12")
    static let panel         = Color(hex: "101522")
    static let panelElevated = Color(hex: "171E2E")
    static let hover         = Color(hex: "1E2840")

    // MARK: Brand accents
    static let primary    = Color(hex: "7C5CFF")  // neural / AI purple
    static let signal     = Color(hex: "22D3C5")  // signal teal
    static let inference  = Color(hex: "4B7BFF")  // inference blue
    static let validation = Color(hex: "5CF2B3")  // success mint
    static let paper      = Color(hex: "8FD3FF")  // paper sky blue

    // MARK: Trading
    static let buy     = Color(hex: "21C784")
    static let sell    = Color(hex: "FF5D7A")
    static let neutral = Color(hex: "94A3B8")

    // MARK: Status
    static let warning     = Color(hex: "FFB547")
    static let errorColor  = Color(hex: "FF5D7A")
    static let stale       = Color(hex: "FFB547")
    static let liveBlocked = Color(hex: "FF5D7A")

    // MARK: Text
    static let textPrimary   = Color(hex: "F6F7FB")
    static let textSecondary = Color(hex: "CBD5E1")
    static let textMuted     = Color(hex: "94A3B8")

    // MARK: Borders
    static let borderSubtle = Color(hex: "253044")
    static let borderStrong = Color(hex: "3B4962")

    // MARK: Dynamic helpers
    static func actionColor(_ action: String) -> Color {
        switch action.lowercased() {
        case "long", "buy":   return buy
        case "short", "sell": return sell
        default:              return neutral
        }
    }

    static func pnlColor(_ value: Double) -> Color { value >= 0 ? buy : sell }

    static func confidenceColor(_ pct: Double) -> Color {
        if pct >= 0.75 { return Color(hex: "5ecf72") }
        if pct >= 0.60 { return Color(hex: "e2bf48") }
        return Color(hex: "ef8f3b")
    }

    static func statusColor(_ status: String) -> Color {
        let s = status.lowercased()
        if s.contains("active") || s.contains("healthy") || s.contains("ok") { return validation }
        if s.contains("degraded") || s.contains("inference") || s.contains("blocked") { return warning }
        if s.contains("error") || s.contains("unavailable") { return errorColor }
        return textMuted
    }
}

// MARK: - Hex Color Initializer
extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 3:  (a, r, g, b) = (255, (int >> 8) * 17, (int >> 4 & 0xF) * 17, (int & 0xF) * 17)
        case 6:  (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8:  (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default: (a, r, g, b) = (255, 0, 0, 0)
        }
        self.init(.sRGB, red: Double(r)/255, green: Double(g)/255, blue: Double(b)/255, opacity: Double(a)/255)
    }
}

// MARK: - Ambient Screen Background (NERVYX MOBILE VISUAL LANGUAGE v2)

/// Ambient screen backdrop: base #070A12 with two soft radial glows
/// (primary purple top-leading, signal teal bottom-trailing) plus a very
/// subtle vertical darkening gradient. Apply via `.nerVyxScreen()` at the
/// SCREEN level only — never stack inside cards.
struct NerVyxScreenBackground: View {
    var body: some View {
        ZStack {
            NerVyx.bg
            GeometryReader { geo in
                let radius = max(geo.size.width, geo.size.height)
                RadialGradient(
                    colors: [NerVyx.primary.opacity(0.08), .clear],
                    center: .topLeading,
                    startRadius: 0,
                    endRadius: radius * 0.85
                )
                RadialGradient(
                    colors: [NerVyx.signal.opacity(0.06), .clear],
                    center: .bottomTrailing,
                    startRadius: 0,
                    endRadius: radius * 0.9
                )
            }
            LinearGradient(
                colors: [.clear, Color.black.opacity(0.22)],
                startPoint: .top,
                endPoint: .bottom
            )
        }
        .ignoresSafeArea()
    }
}

// MARK: - View Modifiers
extension View {
    func nerVyxCard(accent: Color = NerVyx.borderSubtle) -> some View {
        self
            .padding(16)
            .background(NerVyx.panel)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(accent, lineWidth: 1))
    }

    func nerVyxElevatedCard(accent: Color = NerVyx.primary) -> some View {
        self
            .padding(16)
            .background(NerVyx.panelElevated)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(accent.opacity(0.35), lineWidth: 1))
    }

    func nerVyxScreenBackground() -> some View {
        self.background(NerVyx.bg.ignoresSafeArea())
    }

    /// Screen-level ambient background. Replaces `NerVyx.bg.ignoresSafeArea()`.
    func nerVyxScreen() -> some View {
        self.background(NerVyxScreenBackground())
    }

    /// Premium glass card: ultra-thin material over the ambient gradient,
    /// continuous-corner 16pt radius, 1pt white glass edge (0.14 → 0.03)
    /// plus the semantic accent stroke at 0.3 opacity, and a soft shadow.
    /// Use over `.nerVyxScreen()`; safety banners (LIVE BLOCKED, kill switch)
    /// keep their sell-red fills and must NOT migrate to glass.
    func nerVyxGlassCard(accent: Color = NerVyx.borderSubtle, cornerRadius: CGFloat = 16) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        return self
            .padding(16)
            .background(.ultraThinMaterial, in: shape)
            .overlay(
                shape.stroke(
                    LinearGradient(
                        colors: [Color.white.opacity(0.14), Color.white.opacity(0.03)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ),
                    lineWidth: 1
                )
            )
            .overlay(shape.stroke(accent.opacity(0.3), lineWidth: 1))
            .shadow(color: .black.opacity(0.3), radius: 18, y: 8)
    }
}

// MARK: - Reusable Components

struct LivePulse: View {
    var color: Color = NerVyx.signal
    @State private var animating = false

    var body: some View {
        ZStack {
            Circle()
                .fill(color.opacity(0.25))
                .frame(width: 14, height: 14)
                .scaleEffect(animating ? 2.0 : 1.0)
                .opacity(animating ? 0 : 0.7)
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
        }
        .onAppear {
            withAnimation(.default.repeatForever(autoreverses: false)) {
                animating = true
            }
        }
    }
}

struct NerVyxBadge: View {
    let text: String
    var color: Color = NerVyx.primary
    var small: Bool = false

    var body: some View {
        Text(text)
            .font(.system(size: small ? 9 : 11, weight: .bold))
            .foregroundStyle(color)
            .padding(.horizontal, small ? 6 : 8)
            .padding(.vertical, small ? 2 : 4)
            .background(color.opacity(0.15))
            .clipShape(Capsule())
            .overlay(Capsule().stroke(color.opacity(0.4), lineWidth: 1))
    }
}

struct NerVyxStatCard: View {
    let label: String
    let value: String
    var valueColor: Color = NerVyx.textPrimary
    var sublabel: String? = nil
    var accent: Color = NerVyx.primary

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(NerVyx.textMuted)
                .tracking(0.6)
            Text(value)
                .font(.system(size: 20, weight: .bold, design: .monospaced))
                .foregroundStyle(valueColor)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            if let sub = sublabel {
                Text(sub)
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(accent.opacity(0.28), lineWidth: 1))
    }
}

struct ConfidenceBar: View {
    let value: Double

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 3).fill(NerVyx.borderSubtle).frame(height: 5)
                RoundedRectangle(cornerRadius: 3)
                    .fill(NerVyx.confidenceColor(value))
                    .frame(width: geo.size.width * CGFloat(min(max(value, 0), 1)), height: 5)
            }
        }
        .frame(height: 5)
    }
}

struct SectionHeader: View {
    let title: String
    var accent: Color = NerVyx.primary
    var trailing: String? = nil

    var body: some View {
        HStack {
            Rectangle()
                .fill(accent)
                .frame(width: 3, height: 14)
                .clipShape(Capsule())
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(NerVyx.textSecondary)
            if let t = trailing {
                Spacer()
                Text(t)
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
            }
        }
    }
}

struct NerVyxDivider: View {
    var body: some View {
        Rectangle()
            .fill(NerVyx.borderSubtle)
            .frame(height: 1)
            .padding(.vertical, 2)
    }
}

struct DataRow: View {
    let label: String
    let value: String
    var valueColor: Color = NerVyx.textPrimary
    var mono: Bool = false

    var body: some View {
        HStack {
            Text(label)
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textMuted)
            Spacer()
            Text(value)
                .font(mono ? .system(size: 13, design: .monospaced) : .system(size: 13, weight: .medium))
                .foregroundStyle(valueColor)
                .lineLimit(1)
        }
    }
}

// MARK: - Type Scale (NERVYX MOBILE VISUAL LANGUAGE v2)

/// Hero number: 32–38pt heavy monospaced with numeric count-up transitions.
/// Absent data must be passed as "—" (never 0 or a placeholder number).
struct HeroMetricText: View {
    let text: String
    var size: CGFloat = 34
    var color: Color = NerVyx.textPrimary

    var body: some View {
        Text(text)
            .font(.system(size: min(max(size, 32), 38), weight: .heavy, design: .monospaced))
            .foregroundStyle(color)
            .contentTransition(.numericText())
            .lineLimit(1)
            .minimumScaleFactor(0.5)
    }
}

/// Micro-label: 9–10pt semibold uppercase, tracking 0.6.
struct MicroLabel: View {
    let text: String
    var color: Color = NerVyx.textMuted
    var size: CGFloat = 10

    var body: some View {
        Text(text.uppercased())
            .font(.system(size: min(max(size, 9), 10), weight: .semibold))
            .foregroundStyle(color)
            .tracking(0.6)
            .lineLimit(1)
    }
}

/// Compact inline label+value chip for stat strips (glass-friendly).
struct StatChip: View {
    let label: String
    let value: String
    var color: Color = NerVyx.textSecondary
    var accent: Color = NerVyx.borderSubtle

    var body: some View {
        HStack(spacing: 6) {
            MicroLabel(text: label, size: 9)
            Text(value)
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundStyle(color)
                .contentTransition(.numericText())
                .lineLimit(1)
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .background(NerVyx.panel.opacity(0.6))
        .clipShape(Capsule())
        .overlay(Capsule().stroke(accent.opacity(0.35), lineWidth: 1))
    }
}

/// Formatting helper honoring the honesty rule: nil renders "—", never 0.
enum NerVyxFormat {
    static func money(_ value: Double?, decimals: Int = 2, signed: Bool = false) -> String {
        guard let value, value.isFinite else { return "—" }
        // Sign goes BEFORE the dollar: "-$14.41", never "$-14.41".
        let sign = value < 0 ? "-" : (signed && value > 0 ? "+" : "")
        return "\(sign)$\(String(format: "%.\(decimals)f", abs(value)))"
    }

    static func percent(_ fraction: Double?, decimals: Int = 1) -> String {
        guard let fraction, fraction.isFinite else { return "—" }
        return String(format: "%.\(decimals)f%%", fraction * 100)
    }

    static func number(_ value: Double?, decimals: Int = 2) -> String {
        guard let value, value.isFinite else { return "—" }
        return String(format: "%.\(decimals)f", value)
    }

    static func count(_ value: Int?) -> String {
        guard let value else { return "—" }
        return String(value)
    }

    static func compactUSD(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        let absValue = abs(value)
        let sign = value < 0 ? "-" : ""
        switch absValue {
        case 1_000_000_000...: return "\(sign)$\(String(format: "%.1f", absValue / 1_000_000_000))B"
        case 1_000_000...:     return "\(sign)$\(String(format: "%.1f", absValue / 1_000_000))M"
        case 1_000...:         return "\(sign)$\(String(format: "%.1f", absValue / 1_000))K"
        default:               return "\(sign)$\(String(format: "%.2f", absValue))"
        }
    }

    static func age(_ seconds: Double?) -> String {
        guard let seconds, seconds.isFinite, seconds >= 0 else { return "—" }
        if seconds < 60 { return "\(Int(seconds))s" }
        if seconds < 3600 { return "\(Int(seconds / 60))m" }
        if seconds < 86_400 { return String(format: "%.1fh", seconds / 3600) }
        return String(format: "%.1fd", seconds / 86_400)
    }
}
