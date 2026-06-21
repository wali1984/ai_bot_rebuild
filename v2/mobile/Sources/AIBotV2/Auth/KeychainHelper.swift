import Foundation
import Security

/// Secure token storage backed by iOS Keychain.
public final class KeychainHelper {

    public static let shared = KeychainHelper()
    private init() {}

    private let service = "com.aibot.v2.mobile"
    private let tokenAccount = "access_token"
    private let baseURLAccount = "base_url"

    // MARK: - Token

    public func saveToken(_ token: String) {
        save(token, account: tokenAccount)
    }

    public func loadToken() -> String? {
        load(account: tokenAccount)
    }

    public func deleteToken() {
        delete(account: tokenAccount)
    }

    // MARK: - Base URL (user-configurable server address)

    public func saveBaseURL(_ url: String) {
        save(url, account: baseURLAccount)
    }

    public func loadBaseURL() -> String? {
        load(account: baseURLAccount)
    }

    // MARK: - Generic

    private func save(_ value: String, account: String) {
        guard let data = value.data(using: .utf8) else { return }
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
        ]
        SecItemDelete(query as CFDictionary)
        let attributes: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecValueData: data,
            kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        SecItemAdd(attributes as CFDictionary, nil)
    }

    private func load(account: String) -> String? {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess,
              let data = result as? Data,
              let string = String(data: data, encoding: .utf8) else { return nil }
        return string
    }

    private func delete(account: String) {
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
