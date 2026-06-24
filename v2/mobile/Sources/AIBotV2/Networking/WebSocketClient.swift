import Foundation

/// Real-time WebSocket client for market data and execution activity streams.
/// Sends the auth token as a query parameter (WebSocket headers are not supported on all platforms).
@Observable
public final class WebSocketClient: NSObject {

    public enum ConnectionState: Equatable {
        case disconnected, connecting, connected, failed(String)
    }

    public private(set) var state: ConnectionState = .disconnected
    public private(set) var lastMessage: String?

    private var task: URLSessionWebSocketTask?
    private var session: URLSession?
    private var pingTimer: Timer?
    private var onMessage: ((String) -> Void)?

    public static func messages(urlString: String, token: String?) -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { continuation in
            guard let url = authenticatedURL(urlString: urlString, token: token) else {
                continuation.finish(throwing: APIError.websocket("Invalid WebSocket URL"))
                return
            }

            let session = URLSession(configuration: .default)
            let task = session.webSocketTask(with: url)
            task.resume()

            let reader = Task {
                do {
                    while !Task.isCancelled {
                        let message = try await task.receive()
                        switch message {
                        case .string(let text):
                            continuation.yield(text)
                        case .data(let data):
                            if let text = String(data: data, encoding: .utf8) {
                                continuation.yield(text)
                            }
                        @unknown default:
                            continue
                        }
                    }
                    continuation.finish()
                } catch {
                    if Task.isCancelled {
                        continuation.finish()
                    } else {
                        continuation.finish(throwing: error)
                    }
                }
            }

            continuation.onTermination = { @Sendable _ in
                reader.cancel()
                task.cancel(with: .goingAway, reason: nil)
                session.invalidateAndCancel()
            }
        }
    }

    public func connect(urlString: String, token: String?, onMessage: @escaping (String) -> Void) {
        disconnect()
        self.onMessage = onMessage

        guard let url = Self.authenticatedURL(urlString: urlString, token: token) else {
            state = .failed("Invalid WebSocket URL")
            return
        }

        state = .connecting
        let config = URLSessionConfiguration.default
        let urlSession = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        session = urlSession
        let wsTask = urlSession.webSocketTask(with: url)
        task = wsTask
        wsTask.resume()
        receiveNextMessage()
        schedulePing()
    }

    public func disconnect() {
        pingTimer?.invalidate()
        pingTimer = nil
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        session?.invalidateAndCancel()
        session = nil
        state = .disconnected
    }

    // MARK: - Private

    private static func authenticatedURL(urlString: String, token: String?) -> URL? {
        var components = URLComponents(string: urlString)
        if let token {
            var queryItems = components?.queryItems ?? []
            queryItems.append(URLQueryItem(name: "token", value: token))
            components?.queryItems = queryItems
        }
        return components?.url
    }

    private func receiveNextMessage() {
        task?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let message):
                switch message {
                case .string(let text):
                    Task { @MainActor in
                        self.lastMessage = text
                        self.onMessage?(text)
                    }
                case .data(let data):
                    if let text = String(data: data, encoding: .utf8) {
                        Task { @MainActor in
                            self.lastMessage = text
                            self.onMessage?(text)
                        }
                    }
                @unknown default: break
                }
                self.receiveNextMessage()
            case .failure(let error):
                Task { @MainActor in
                    self.state = .failed(error.localizedDescription)
                }
            }
        }
    }

    private func schedulePing() {
        pingTimer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
            self?.task?.sendPing { _ in }
        }
    }
}

extension WebSocketClient: URLSessionWebSocketDelegate {
    public func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
        Task { @MainActor in self.state = .connected }
    }

    public func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        Task { @MainActor in self.state = .disconnected }
    }
}
