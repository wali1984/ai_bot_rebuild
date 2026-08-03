import Foundation

/// Decodes GET /api/v2/adaptive/status (schema `adaptive_status_v1`).
///
/// Only the stable envelope fields are decoded — per-section availability and
/// freshness — so the screen surfaces honest subsystem health without touching
/// the arbitrary per-section `data` blob. Unknown JSON keys are ignored by
/// Codable. Property names are snake_case to match the JSON with the default
/// decoder, consistent with the rest of the app's DTOs.
public struct AdaptiveStatusResponse: Codable {
    public let schema_version: String?
    public let summary: AdaptiveStatusSummary?
    public let sections: [String: AdaptiveStatusSection]?
    public let live_gate: String?
    public let generated_at_utc: String?
}

public struct AdaptiveStatusSummary: Codable {
    public let section_total: Int?
    public let fresh_count: Int?
    public let stale_count: Int?
    public let absent_count: Int?
}

public struct AdaptiveStatusSection: Codable {
    public let available: Bool?
    public let source_key: String?
    public let age_seconds: Double?
    public let stale: Bool?
    public let reason: String?
    public let live_gate: String?
}
