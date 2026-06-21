import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// Async HTTP client. Compiles on Linux (swift-corelibs-foundation) and Apple platforms.
public actor APIClient {

    public static let shared = APIClient()
    private let session: URLSession

    private init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest  = 20
        config.timeoutIntervalForResource = 40
        session = URLSession(configuration: config)
    }

    // MARK: - Public

    public func get<T: Decodable>(
        path: String,
        queryItems: [URLQueryItem] = [],
        token: String?,
        baseURL: String
    ) async throws -> T {
        let url = try buildURL(base: baseURL, path: path, queryItems: queryItems)
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        setHeaders(&req, token: token)
        return try await execute(req)
    }

    @discardableResult
    public func post<Body: Encodable, Response: Decodable>(
        path: String,
        body: Body,
        token: String?,
        baseURL: String
    ) async throws -> Response {
        let url = try buildURL(base: baseURL, path: path)
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        setHeaders(&req, token: token)
        req.httpBody = try JSONEncoder().encode(body)
        return try await execute(req)
    }

    // MARK: - Private

    private func buildURL(base: String, path: String, queryItems: [URLQueryItem] = []) throws -> URL {
        guard var comps = URLComponents(string: base + path) else {
            throw APIError.badURL(base + path)
        }
        if !queryItems.isEmpty { comps.queryItems = queryItems }
        guard let url = comps.url else { throw APIError.badURL(base + path) }
        return url
    }

    private func setHeaders(_ req: inout URLRequest, token: String?) {
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue("AIBotV2-CLI/1.0", forHTTPHeaderField: "User-Agent")
        if let t = token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
    }

    private func execute<T: Decodable>(_ req: URLRequest) async throws -> T {
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw APIError.noResponse }
        if http.statusCode == 401 { throw APIError.unauthorized }
        guard (200...299).contains(http.statusCode) else {
            let detail = (try? JSONDecoder().decode(ErrorBody.self, from: data))?.detail
                ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            throw APIError.http(statusCode: http.statusCode, message: detail)
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error.localizedDescription)
        }
    }
}

private struct ErrorBody: Decodable { let detail: String? }
