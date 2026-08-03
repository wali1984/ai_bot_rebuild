import SwiftUI

// MARK: - StalenessChip (shared freshness truth chip)
//
// Every screen surfaces the envelope truth fields (stale, lag_ms, transport,
// source_type) through this chip. Hardcoded "LIVE" labels are forbidden —
// the mode must always be derived from real snapshot metadata.
//
//   REALTIME  — green pulse   (WebSocket stream, fresh)
//   POLL      — inference blue (HTTP poll, fresh)
//   STALE     — amber + age text
//   OFFLINE   — sell red (no data / transport down)

enum FreshnessMode: String {
    case realtime = "REALTIME"
    case poll = "POLL"
    case stale = "STALE"
    case offline = "OFFLINE"
}

struct StalenessChip: View {
    let mode: FreshnessMode
    var ageText: String? = nil

    private var color: Color {
        switch mode {
        case .realtime: return NerVyx.validation
        case .poll:     return NerVyx.inference
        case .stale:    return NerVyx.stale
        case .offline:  return NerVyx.sell
        }
    }

    var body: some View {
        HStack(spacing: 5) {
            if mode == .realtime {
                LivePulse(color: color)
                    .frame(width: 10, height: 10)
            } else {
                Circle()
                    .fill(color)
                    .frame(width: 6, height: 6)
            }
            Text(label)
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(color)
                .tracking(0.6)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(color.opacity(0.12))
        .clipShape(Capsule())
        .overlay(Capsule().stroke(color.opacity(0.4), lineWidth: 1))
        .accessibilityIdentifier("staleness-chip-\(mode.rawValue.lowercased())")
    }

    private var label: String {
        if mode == .stale, let ageText, !ageText.isEmpty {
            return "STALE · \(ageText)"
        }
        return mode.rawValue
    }
}

extension StalenessChip {
    /// Derive the chip from decoded MobileResourceSnapshot metadata.
    /// - stale: envelope `stale` flag (amber wins over transport)
    /// - transport "websocket"/"ws" + fresh → REALTIME
    /// - fresh via HTTP → POLL
    /// - no payload / error → OFFLINE (use `offline()` helper)
    static func from(
        stale: Bool,
        lagMs: Double? = nil,
        transport: String? = nil,
        ageSeconds: Double? = nil
    ) -> StalenessChip {
        if stale {
            let age = ageSeconds ?? lagMs.map { $0 / 1000 }
            return StalenessChip(mode: .stale, ageText: age.map { NerVyxFormat.age($0) })
        }
        let t = (transport ?? "").lowercased()
        if t.contains("ws") || t.contains("websocket") || t.contains("stream") {
            return StalenessChip(mode: .realtime)
        }
        return StalenessChip(mode: .poll)
    }

    static func offline() -> StalenessChip {
        StalenessChip(mode: .offline)
    }
}
