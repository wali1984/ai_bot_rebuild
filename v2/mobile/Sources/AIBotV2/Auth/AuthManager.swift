import Foundation
import Observation

/// JWT auth state manager. Persists token in Keychain.
/// Exposed via @Environment(\.authManager) in all views.
/// @MainActor-isolated like every ViewModel: `state` drives SwiftUI, so it must
/// only be mutated on the main actor (init()'s Task and the async methods below
/// otherwise race SwiftUI's main-actor reads).
@MainActor
@Observable
public final class AuthManager {

    public enum AuthState: Equatable {
        case loggedOut
        case loading
        case loggedIn(UserSession)
        case error(String)
    }

    public struct UserSession: Equatable, Codable {
        public let accessToken: String
        public let email: String
        public let role: String
        public let userId: String

        public var isAdmin: Bool { role == "admin" || role == "superadmin" }
        public var isSuperadmin: Bool { role == "superadmin" }
        public var isTrader: Bool { ["trader", "admin", "superadmin"].contains(role) }
    }

    public private(set) var state: AuthState = .loggedOut
    private let keychain = KeychainHelper.shared

    public init() {
        if let token = keychain.loadToken() {
            state = .loading
            Task { await restoreSession(token: token) }
        }
    }

    // MARK: - Login

    public func login(email: String, password: String, baseURL: String) async {
        state = .loading
        do {
            let session = try await performLogin(email: email, password: password, baseURL: baseURL)
            keychain.saveToken(session.accessToken)
            keychain.saveBaseURL(baseURL)
            state = .loggedIn(session)
        } catch let err as APIError {
            state = .error(err.message)
        } catch {
            state = .error(error.localizedDescription)
        }
    }

    public func logout(baseURL: String) async {
        if case .loggedIn(let session) = state {
            _ = try? await APIClient.shared.post(
                path: APIEndpoints.logout,
                body: Empty(),
                token: session.accessToken,
                baseURL: baseURL
            ) as Empty
        }
        keychain.deleteToken()
        state = .loggedOut
    }

    public func currentToken() -> String? {
        if case .loggedIn(let session) = state {
            return session.accessToken
        }
        return nil
    }

    public var currentSession: UserSession? {
        if case .loggedIn(let session) = state { return session }
        return nil
    }

    // MARK: - Private

    private func performLogin(email: String, password: String, baseURL: String) async throws -> UserSession {
        struct LoginBody: Encodable { let email: String; let password: String }
        struct LoginResponse: Decodable {
            let access_token: String
            let user: UserPayload
        }
        struct UserPayload: Decodable {
            let id: String          // backend safe_user() returns "id", not "user_id"
            let email: String
            let role: String
        }
        let response: LoginResponse = try await APIClient.shared.post(
            path: APIEndpoints.login,
            body: LoginBody(email: email, password: password),
            token: nil,
            baseURL: baseURL
        )
        return UserSession(
            accessToken: response.access_token,
            email: response.user.email,
            role: response.user.role,
            userId: response.user.id
        )
    }

    private func restoreSession(token: String) async {
        guard let baseURL = keychain.loadBaseURL() else {
            state = .loggedOut
            return
        }
        do {
            struct MeResponse: Decodable {
                let id: String      // backend safe_user() returns "id", not "user_id"
                let email: String
                let role: String
            }
            let me: MeResponse = try await APIClient.shared.get(
                path: APIEndpoints.me,
                token: token,
                baseURL: baseURL
            )
            let session = UserSession(
                accessToken: token,
                email: me.email,
                role: me.role,
                userId: me.id
            )
            state = .loggedIn(session)
        } catch {
            keychain.deleteToken()
            state = .loggedOut
        }
    }
}

private struct Empty: Codable {}
