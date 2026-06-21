import Foundation

/// Central HTTP client. Uses URLSession with Bearer token auth.
/// Throws APIError for all non-2xx responses.
public actor APIClient {

    public static let shared = APIClient()
    private let session: URLSession

    private init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 30
        config.waitsForConnectivity = true
        session = URLSession(configuration: config)
    }

    // MARK: - GET

    public func get<T: Decodable>(
        path: String,
        queryItems: [URLQueryItem] = [],
        token: String?,
        baseURL: String
    ) async throws -> T {
        let url = try buildURL(base: baseURL, path: path, queryItems: queryItems)
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        setHeaders(&request, token: token)
        return try await execute(request)
    }

    // MARK: - POST

    @discardableResult
    public func post<Body: Encodable, Response: Decodable>(
        path: String,
        body: Body,
        token: String?,
        baseURL: String
    ) async throws -> Response {
        let url = try buildURL(base: baseURL, path: path)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        setHeaders(&request, token: token)
        request.httpBody = try JSONEncoder().encode(body)
        return try await execute(request)
    }

    // MARK: - DELETE

    @discardableResult
    public func delete<Response: Decodable>(
        path: String,
        token: String?,
        baseURL: String
    ) async throws -> Response {
        let url = try buildURL(base: baseURL, path: path)
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        setHeaders(&request, token: token)
        return try await execute(request)
    }

    // MARK: - Private

    private func buildURL(base: String, path: String, queryItems: [URLQueryItem] = []) throws -> URL {
        var components = URLComponents(string: base + path) ?? URLComponents()
        if !queryItems.isEmpty { components.queryItems = queryItems }
        guard let url = components.url else { throw APIError.badURL(base + path) }
        return url
    }

    private func setHeaders(_ request: inout URLRequest, token: String?) {
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("AIBotV2-iOS/1.0", forHTTPHeaderField: "User-Agent")
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
    }

    private func execute<T: Decodable>(_ request: URLRequest) async throws -> T {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.noResponse }
        guard (200...299).contains(http.statusCode) else {
            let detail = (try? JSONDecoder().decode(ErrorBody.self, from: data))?.detail ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            throw APIError.http(statusCode: http.statusCode, message: detail)
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error.localizedDescription)
        }
    }
}

// MARK: - Errors

public enum APIError: Error, LocalizedError {
    case badURL(String)
    case noResponse
    case http(statusCode: Int, message: String)
    case decoding(String)
    case websocket(String)

    public var errorDescription: String? { message }

    public var message: String {
        switch self {
        case .badURL(let u): return "Invalid URL: \(u)"
        case .noResponse: return "No response from server"
        case .http(let code, let msg): return "HTTP \(code): \(msg)"
        case .decoding(let msg): return "Decode error: \(msg)"
        case .websocket(let msg): return "WebSocket error: \(msg)"
        }
    }

    public var isUnauthorized: Bool {
        if case .http(let code, _) = self { return code == 401 }
        return false
    }
}

private struct ErrorBody: Decodable { let detail: String? }
