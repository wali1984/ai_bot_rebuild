import Foundation

/// Auth state — platform-agnostic (no Keychain, no SwiftUI).
public final class AuthManager: @unchecked Sendable {

    public enum State: Sendable {
        case loggedOut
        case loading
        case loggedIn(Session)
        case error(String)
    }

    public struct Session: Sendable, Codable {
        public let accessToken: String
        public let email: String
        public let role: String
        public let userId: String

        public var isAdmin: Bool      { ["admin", "superadmin"].contains(role) }
        public var isSuperadmin: Bool { role == "superadmin" }
        public var isTrader: Bool     { ["trader", "admin", "superadmin"].contains(role) }
    }

    public private(set) var state: State = .loggedOut
    private let store = TokenStore.shared

    public init() {}

    // MARK: - Login

    @discardableResult
    public func login(email: String, password: String, baseURL: String) async -> Session? {
        state = .loading
        do {
            let session = try await performLogin(email: email, password: password, baseURL: baseURL)
            store.saveToken(session.accessToken)
            store.saveBaseURL(baseURL)
            state = .loggedIn(session)
            return session
        } catch {
            state = .error(error.localizedDescription)
            return nil
        }
    }

    public func logout(baseURL: String) async {
        if case .loggedIn(let s) = state {
            _ = try? await APIClient.shared.post(
                path: APIEndpoints.logout, body: Empty(), token: s.accessToken, baseURL: baseURL
            ) as Empty
        }
        store.deleteToken()
        state = .loggedOut
    }

    public func currentToken() -> String? {
        if case .loggedIn(let s) = state { return s.accessToken }
        return nil
    }

    public var currentSession: Session? {
        if case .loggedIn(let s) = state { return s }
        return nil
    }

    // MARK: - Restore from stored token

    public func restoreSession() async {
        guard let token = store.loadToken(),
              let baseURL = store.loadBaseURL() else { return }
        state = .loading
        do {
            let me: MeResponse = try await APIClient.shared.get(
                path: APIEndpoints.me, token: token, baseURL: baseURL
            )
            state = .loggedIn(Session(
                accessToken: token, email: me.email, role: me.role, userId: me.user_id
            ))
        } catch {
            store.deleteToken()
            state = .loggedOut
        }
    }

    // MARK: - Private

    private struct LoginBody:  Encodable { let email: String; let password: String }
    private struct LoginResp:  Decodable { let access_token: String; let user: UserPayload }
    private struct UserPayload: Decodable { let user_id: String; let email: String; let role: String }
    private struct MeResponse:  Decodable { let user_id: String; let email: String; let role: String }

    private func performLogin(email: String, password: String, baseURL: String) async throws -> Session {
        let resp: LoginResp = try await APIClient.shared.post(
            path: APIEndpoints.login,
            body: LoginBody(email: email, password: password),
            token: nil,
            baseURL: baseURL
        )
        return Session(
            accessToken: resp.access_token,
            email: resp.user.email,
            role: resp.user.role,
            userId: resp.user.user_id
        )
    }
}

private struct Empty: Codable {}
