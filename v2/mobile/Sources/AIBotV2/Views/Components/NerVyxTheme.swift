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
            withAnimation(.easeOut(duration: 1.6).repeatForever(autoreverses: false)) {
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
