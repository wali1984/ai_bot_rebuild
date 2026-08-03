import Foundation
import UserNotifications
#if os(iOS)
import UIKit
#endif

/// Handles push notification registration and local alert delivery.
@Observable
public final class NotificationManager {

    public static let shared = NotificationManager()
    public private(set) var isAuthorized = false
    public private(set) var deviceToken: String?

    private init() {}

    public func requestAuthorization() async {
        do {
            let granted = try await UNUserNotificationCenter.current()
                .requestAuthorization(options: [.alert, .sound, .badge])
            isAuthorized = granted
        } catch {
            isAuthorized = false
        }
    }

    public func setDeviceToken(_ data: Data) {
        let token = data.map { String(format: "%02x", $0) }.joined()
        deviceToken = token
    }

    /// Register device token with the backend.
    public func registerWithBackend(token: String, baseURL: String) async {
        guard let deviceToken else { return }
        struct RegBody: Encodable {
            let device_token: String
            let platform: String
            let environment: String
            let app_version: String
        }
        let body = RegBody(
            device_token: deviceToken,
            platform: "apns",
            environment: "production",
            app_version: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        )
        struct RegResponse: Decodable { let status: String }
        _ = try? await APIClient.shared.post(
            path: APIEndpoints.mobilePushRegister,
            body: body,
            token: token,
            baseURL: baseURL
        ) as RegResponse
    }

    /// Show a local notification for a critical alert.
    public func sendLocalAlert(title: String, body: String, identifier: String = UUID().uuidString) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .defaultCritical
        let request = UNNotificationRequest(identifier: identifier, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request, withCompletionHandler: nil)
    }
}
