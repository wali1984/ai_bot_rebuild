import SwiftUI
import Observation

public enum NervyxBrand {
    public static let productName = NervyxGeneratedThemeManifest.productName
    public static let descriptor = NervyxGeneratedThemeManifest.descriptor
    public static let tagline = NervyxGeneratedThemeManifest.tagline
    public static let secondaryLine = NervyxGeneratedThemeManifest.secondaryLine
    public static let paperStatus = NervyxGeneratedThemeManifest.secondaryLine
    public static let liveBlockedLabel = "Operator gated"
}

public enum NervyxModule: String, CaseIterable, Identifiable {
    case sense
    case core
    case shift
    case guard
    case replay
    case execute
    case observe

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .sense: return "NERVYX SENSE"
        case .core: return "NERVYX CORE"
        case .shift: return "NERVYX SHIFT"
        case .guard: return "NERVYX GUARD"
        case .replay: return "NERVYX REPLAY"
        case .execute: return "NERVYX EXECUTE"
        case .observe: return "NERVYX OBSERVE"
        }
    }

    public var description: String {
        switch self {
        case .sense: return "Data ingestion and market-state trust"
        case .core: return "PPO + MASA inference"
        case .shift: return "Regime and strategy routing"
        case .guard: return "Risk, trust, and execution gates"
        case .replay: return "Decision evidence and reconstruction"
        case .execute: return "Execution lifecycle"
        case .observe: return "Monitoring, soak, and operational proof"
        }
    }
}

public enum NervyxTheme: String, CaseIterable, Identifiable {
    case midnightNeural
    case polarSignal
    case opsTerminal

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .midnightNeural: return "Midnight Neural"
        case .polarSignal: return "Polar Signal"
        case .opsTerminal: return "Ops Terminal"
        }
    }
}

@Observable
public final class NervyxThemeManager {
    public private(set) var selectedTheme: NervyxTheme = .midnightNeural

    public init() {}

    public func select(_ theme: NervyxTheme, backendConfirmedAdmin: Bool) {
        if theme == .opsTerminal && !backendConfirmedAdmin {
            selectedTheme = .midnightNeural
            return
        }
        selectedTheme = theme
    }
}

public enum NervyxColors {
    public static let brandPrimary = Color(hex: NervyxGeneratedTokens.brandPrimary)
    public static let signalAccent = Color(hex: NervyxGeneratedTokens.signalAccent)
    public static let validationAccent = Color(hex: NervyxGeneratedTokens.validationAccent)
    public static let backgroundBase = Color(hex: NervyxGeneratedTokens.backgroundBase)
    public static let panel = Color(hex: NervyxGeneratedTokens.panel)
    public static let textPrimary = Color(hex: NervyxGeneratedTokens.textPrimary)
    public static let textMuted = Color(hex: NervyxGeneratedTokens.textMuted)
    public static let buy = Color(hex: NervyxGeneratedTokens.buy)
    public static let sell = Color(hex: NervyxGeneratedTokens.sell)
    public static let warning = Color(hex: NervyxGeneratedTokens.warning)
    public static let liveBlocked = Color(hex: NervyxGeneratedTokens.liveBlocked)
}

public enum NervyxTypography {
    public static let display = Font.system(.largeTitle, design: .rounded).weight(.bold)
    public static let title = Font.system(.title2, design: .rounded).weight(.semibold)
    public static let body = Font.system(.body, design: .default)
    public static let data = Font.system(.caption, design: .monospaced)
}

public enum NervyxSpacing {
    public static let sm: CGFloat = 8
    public static let md: CGFloat = 12
    public static let lg: CGFloat = 16
    public static let xl: CGFloat = 24
}

public enum NervyxElevation {
    public static let panelShadowRadius: CGFloat = 18
}

public enum NervyxAssets {
    public static let mark = "NervyxMark"
    public static let logoOnMidnight = "NervyxLogoOnMidnight"
    public static let logoOnLight = "NervyxLogoOnLight"
}

public enum NervyxStatusStyle {
    case live
    case paper
    case blocked
    case stale
    case offline

    public var label: String {
        switch self {
        case .live: return "Live"
        case .paper: return "Live"
        case .blocked: return "Blocked"
        case .stale: return "Stale"
        case .offline: return "Offline"
        }
    }

    public var color: Color {
        switch self {
        case .live: return NervyxColors.validationAccent
        case .paper: return NervyxColors.signalAccent
        case .blocked: return NervyxColors.liveBlocked
        case .stale: return NervyxColors.warning
        case .offline: return NervyxColors.textMuted
        }
    }
}

private extension Color {
    init(hex: String) {
        let cleaned = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        var value: UInt64 = 0
        Scanner(string: cleaned).scanHexInt64(&value)
        let red = Double((value >> 16) & 0xFF) / 255.0
        let green = Double((value >> 8) & 0xFF) / 255.0
        let blue = Double(value & 0xFF) / 255.0
        self.init(red: red, green: green, blue: blue)
    }
}
