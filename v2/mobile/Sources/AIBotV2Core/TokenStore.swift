import Foundation

/// Persists auth token and server URL.
/// On Linux: JSON file in ~/.config/aibot/credentials.json
/// On Apple platforms: delegates to Keychain (override via subclass in iOS target)
public class TokenStore: @unchecked Sendable {

    public static let shared: TokenStore = TokenStore()

    private let configDir: URL
    private let configFile: URL

    private struct Config: Codable {
        var token: String?
        var baseURL: String?
    }

    public init() {
        #if os(Linux)
        let base = URL(fileURLWithPath: ProcessInfo.processInfo.environment["HOME"] ?? "/tmp")
        configDir  = base.appendingPathComponent(".config/aibot")
        #else
        configDir  = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
                        .first!.appendingPathComponent("AIBotV2")
        #endif
        configFile = configDir.appendingPathComponent("credentials.json")
        try? FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
    }

    // MARK: - Token

    public func saveToken(_ token: String) {
        var c = load()
        c.token = token
        save(c)
    }

    public func loadToken() -> String? { load().token }
    public func deleteToken() { var c = load(); c.token = nil; save(c) }

    // MARK: - Base URL

    public func saveBaseURL(_ url: String) {
        var c = load()
        c.baseURL = url
        save(c)
    }

    public func loadBaseURL() -> String? { load().baseURL }

    // MARK: - Private

    private func load() -> Config {
        guard let data = try? Data(contentsOf: configFile),
              let config = try? JSONDecoder().decode(Config.self, from: data) else {
            return Config()
        }
        return config
    }

    private func save(_ config: Config) {
        guard let data = try? JSONEncoder().encode(config) else { return }
        try? data.write(to: configFile, options: .atomic)
    }
}

/// Application-level config derived from TokenStore.
public enum AppConfig {
    public static var baseURL: String {
        get { TokenStore.shared.loadBaseURL() ?? "http://127.0.0.1:5173" }
        set { TokenStore.shared.saveBaseURL(newValue) }
    }
    public static var baseWSURL: String {
        baseURL.replacingOccurrences(of: "http://", with: "ws://")
               .replacingOccurrences(of: "https://", with: "wss://")
    }
}
