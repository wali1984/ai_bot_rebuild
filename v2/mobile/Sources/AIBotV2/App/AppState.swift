import Foundation
import Observation

/// Central app-level state shared across all views.
/// Injected via @Environment in AIBotV2App.
/// @MainActor-isolated: it holds @MainActor @Observable managers (AuthManager)
/// and drives SwiftUI, so its stored-property initializers must run on the main
/// actor. Without this, `auth = AuthManager()` calls a main-actor init from a
/// nonisolated context (Swift 6 strict concurrency error).
@MainActor
@Observable
public final class AppState {

    public let auth = AuthManager()
    public private(set) var baseURL: String = AppConfiguration.baseURL
    public var selectedTab: AppTab = .dashboard

    public func setBaseURL(_ url: String) {
        AppConfiguration.baseURL = url
        baseURL = url
    }

    public func selectTab(_ tab: AppTab) {
        selectedTab = tab
    }

    public var wsBaseURL: String {
        baseURL.replacingOccurrences(of: "http://", with: "ws://")
               .replacingOccurrences(of: "https://", with: "wss://")
    }
}

public enum AppTab: Hashable {
    case dashboard
    case positions
    case signals
    case paper
    case risk
    case alerts
    case monitor
    case serviceHealth
    case providers
    case admin
    case settings
    case predictions
    case activity
    case readiness
    case audit
    case backtestReplay
    case markets
    case derivatives
    case trainerTelemetry
}
