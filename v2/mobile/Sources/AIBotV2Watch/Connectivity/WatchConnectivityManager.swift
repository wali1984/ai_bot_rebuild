import Foundation
import WatchConnectivity

/// Manages WatchConnectivity session between iPhone and Apple Watch.
/// On iPhone: sends system state to Watch when data refreshes.
/// On Watch: receives data from iPhone and triggers UI updates.
final class WatchConnectivityManager: NSObject, WCSessionDelegate {

    static let shared = WatchConnectivityManager()

    var onDataReceived: (([String: Any]) -> Void)?
    var onReachabilityChanged: ((Bool) -> Void)?
    private var session: WCSession?

    private override init() { super.init() }

    func activate() {
        guard WCSession.isSupported() else { return }
        let s = WCSession.default
        s.delegate = self
        s.activate()
        session = s
    }

    /// iPhone → Watch: send compact system state
    func sendSystemState(_ payload: [String: Any]) {
        guard let s = session, s.activationState == .activated, s.isReachable else { return }
        s.sendMessage(payload, replyHandler: nil, errorHandler: nil)
    }

    /// Watch → iPhone: request refresh
    func sendMessage(_ message: [String: Any]) {
        guard let s = session, s.activationState == .activated else { return }
        if s.isReachable {
            s.sendMessage(message, replyHandler: nil, errorHandler: nil)
        } else {
            try? s.updateApplicationContext(message)
        }
    }

    // MARK: - WCSessionDelegate

    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {}

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        DispatchQueue.main.async { self.onDataReceived?(message) }
    }

    func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        DispatchQueue.main.async { self.onDataReceived?(applicationContext) }
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async { self.onReachabilityChanged?(session.isReachable) }
    }

#if os(iOS)
    func sessionDidBecomeInactive(_ session: WCSession) {}
    func sessionDidDeactivate(_ session: WCSession) { session.activate() }
#endif
}
