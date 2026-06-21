import SwiftUI
import WatchKit

@main
struct AIBotV2WatchApp: App {
    @WKApplicationDelegateAdaptor(WatchAppDelegate.self) var delegate
    @StateObject private var watchState = WatchAppState()

    var body: some Scene {
        WindowGroup {
            WatchRootView()
                .environmentObject(watchState)
        }
    }
}

class WatchAppDelegate: NSObject, WKApplicationDelegate {
    func applicationDidFinishLaunching() {
        WatchConnectivityManager.shared.activate()
    }
}

/// Central watchOS app state — receives data from iPhone companion app via WatchConnectivity.
class WatchAppState: ObservableObject {
    @Published var dashboard: WatchDashboardData?
    @Published var positions: [WatchPosition] = []
    @Published var alerts: [WatchAlert] = []
    @Published var isConnectedToPhone = false
    @Published var lastUpdated: Date?

    init() {
        WatchConnectivityManager.shared.onDataReceived = { [weak self] data in
            DispatchQueue.main.async {
                self?.handleData(data)
            }
        }
        WatchConnectivityManager.shared.onReachabilityChanged = { [weak self] reachable in
            DispatchQueue.main.async {
                self?.isConnectedToPhone = reachable
            }
        }
    }

    private func handleData(_ data: [String: Any]) {
        if let dashDict = data["dashboard"] as? [String: Any] {
            dashboard = WatchDashboardData(from: dashDict)
            lastUpdated = Date()
        }
        if let posArray = data["positions"] as? [[String: Any]] {
            positions = posArray.compactMap { WatchPosition(from: $0) }
        }
        if let alertArray = data["alerts"] as? [[String: Any]] {
            alerts = alertArray.compactMap { WatchAlert(from: $0) }
        }
    }

    func requestRefresh() {
        WatchConnectivityManager.shared.sendMessage(["action": "refresh"])
    }
}
