import Foundation

#if canImport(WatchConnectivity)
import WatchConnectivity
#endif

#if os(iOS) && canImport(WatchConnectivity)
final class WatchSyncCenter: NSObject, WCSessionDelegate {
    static let shared = WatchSyncCenter()

    private var session: WCSession?
    private var dashboardPayload: [String: Any]?
    private var positionsPayload: [[String: Any]] = []
    private var alertsPayload: [[String: Any]] = []

    private override init() {
        super.init()
        activate()
    }

    func activate() {
        guard WCSession.isSupported() else { return }
        let nextSession = WCSession.default
        nextSession.delegate = self
        nextSession.activate()
        session = nextSession
    }

    func updateDashboard(_ dashboard: MobileDashboard?, health: MobileHealth?) {
        guard let dashboard else { return }
        dashboardPayload = [
            "overall": health?.overall ?? (dashboard.redis_connected ? "healthy" : "degraded"),
            "trainer_active": dashboard.trainer.isActive,
            "gpu_utilization": dashboard.gpu.utilization_pct,
            "open_positions": dashboard.paper.open_positions,
            "total_pnl": dashboard.paper.total_pnl,
            "realized_pnl": dashboard.paper.realized_pnl_usd,
            "unrealized_pnl": dashboard.paper.unrealized_pnl_usd,
            "signals_seen": dashboard.paper.signals_seen,
            "intents_accepted": dashboard.paper.intents_accepted,
            "intents_blocked": dashboard.paper.intents_blocked,
            "live_blocked": !dashboard.live_gate.places_real_order,
            "last_updated": health?.generated_utc ?? dashboard.generated_utc,
        ]
        publishCurrentSnapshot()
    }

    func updatePositions(_ response: MobilePositionsResponse?) {
        positionsPayload = (response?.positions ?? []).map { position in
            [
                "id": position.id,
                "symbol": position.symbol,
                "side": position.side,
                "unrealized_pnl": position.unrealized_pnl,
                "entry_price": position.entry_price,
                "mark_price": position.mark_price,
            ]
        }
        publishCurrentSnapshot()
    }

    func updateAlerts(_ response: MobileAlertsResponse?) {
        alertsPayload = (response?.alerts ?? []).map { alert in
            [
                "id": alert.id,
                "symbol": alert.symbol,
                "type": alert.type,
                "severity": alert.severity,
                "message": alert.message,
            ]
        }
        publishCurrentSnapshot()
    }

    private func publishCurrentSnapshot() {
        guard let session, session.activationState == .activated else { return }
        var payload: [String: Any] = [:]
        if let dashboardPayload { payload["dashboard"] = dashboardPayload }
        payload["positions"] = positionsPayload
        payload["alerts"] = alertsPayload
        guard !payload.isEmpty else { return }

        if session.isReachable {
            session.sendMessage(payload, replyHandler: nil, errorHandler: nil)
        } else {
            try? session.updateApplicationContext(payload)
        }
    }

    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        if activationState == .activated {
            publishCurrentSnapshot()
        }
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        handleWatchMessage(message)
    }

    func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        handleWatchMessage(applicationContext)
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        if session.isReachable {
            publishCurrentSnapshot()
        }
    }

    private func handleWatchMessage(_ message: [String: Any]) {
        if (message["action"] as? String) == "refresh" {
            publishCurrentSnapshot()
        }
    }

    func sessionDidBecomeInactive(_ session: WCSession) {}
    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }
}
#else
final class WatchSyncCenter {
    static let shared = WatchSyncCenter()

    func updateDashboard(_ dashboard: MobileDashboard?, health: MobileHealth?) {}
    func updatePositions(_ response: MobilePositionsResponse?) {}
    func updateAlerts(_ response: MobileAlertsResponse?) {}
}
#endif
