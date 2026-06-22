import Foundation

struct MobileResourceEnvelope<T: Decodable>: Decodable {
    let data: T?
    let stale: Bool?
}

func decodeMobileResourceMessage<T: Decodable>(_ type: T.Type, from message: String) throws -> T {
    let data = Data(message.utf8)
    let decoder = JSONDecoder()
    if let envelope = try? decoder.decode(MobileResourceEnvelope<T>.self, from: data),
       let payload = envelope.data {
        return payload
    }
    return try decoder.decode(T.self, from: data)
}
