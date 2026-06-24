import Foundation

struct MobileResourceEnvelope<T: Decodable>: Decodable {
    let ok: Bool?
    let data: T?
    let source: String?
    let source_type: String?
    let endpoint: String?
    let timestamp: String?
    let received_at: String?
    let lag_ms: Double?
    let stale: Bool?
    let missing_fields: [String]?
    let warnings: [String]?
    let transport: String?
    let resource_path: String?
}

struct MobileResourceSnapshot<T> {
    let payload: T
    let ok: Bool?
    let source: String?
    let sourceType: String?
    let endpoint: String?
    let timestamp: String?
    let receivedAt: String?
    let lagMs: Double?
    let stale: Bool
    let missingFields: [String]
    let warnings: [String]
    let transport: String?
    let resourcePath: String?
}

func decodeMobileResourceSnapshot<T: Decodable>(_ type: T.Type, from message: String) throws -> MobileResourceSnapshot<T> {
    let data = Data(message.utf8)
    let decoder = JSONDecoder()
    let envelope = try? decoder.decode(MobileResourceEnvelope<T>.self, from: data)
    let payload: T
    if let wrapped = envelope?.data {
        payload = wrapped
    } else {
        payload = try decoder.decode(T.self, from: data)
    }

    return MobileResourceSnapshot(
        payload: payload,
        ok: envelope?.ok,
        source: envelope?.source,
        sourceType: envelope?.source_type,
        endpoint: envelope?.endpoint,
        timestamp: envelope?.timestamp,
        receivedAt: envelope?.received_at,
        lagMs: envelope?.lag_ms,
        stale: envelope?.stale ?? false,
        missingFields: envelope?.missing_fields ?? [],
        warnings: envelope?.warnings ?? [],
        transport: envelope?.transport,
        resourcePath: envelope?.resource_path
    )
}

func decodeMobileResourceMessage<T: Decodable>(_ type: T.Type, from message: String) throws -> T {
    try decodeMobileResourceSnapshot(type, from: message).payload
}
