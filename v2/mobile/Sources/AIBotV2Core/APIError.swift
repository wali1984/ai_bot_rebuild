import Foundation

public enum APIError: Error, Sendable {
    case badURL(String)
    case noResponse
    case http(statusCode: Int, message: String)
    case decoding(String)
    case websocket(String)
    case unauthorized

    public var message: String {
        switch self {
        case .badURL(let u):          return "Invalid URL: \(u)"
        case .noResponse:             return "No response from server"
        case .http(let c, let msg):   return "HTTP \(c): \(msg)"
        case .decoding(let msg):      return "Decode error: \(msg)"
        case .websocket(let msg):     return "WebSocket: \(msg)"
        case .unauthorized:           return "Unauthorized — please sign in"
        }
    }

    public var isUnauthorized: Bool {
        if case .http(let code, _) = self { return code == 401 }
        if case .unauthorized = self { return true }
        return false
    }
}

extension APIError: LocalizedError {
    public var errorDescription: String? { message }
}
