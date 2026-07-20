import SwiftUI

// MARK: - Self-Healing Banner (shared component)
//
// Extracted from ServiceHealthView so any screen (Dashboard, Service Health,
// System Monitor) can drop it in. Renders only when a service is still down
// after the self-healing supervisor's auto-recovery, or the supervisor is
// stale. This is a safety surface: keep the sell-red/amber fills — do NOT
// migrate it to the glass card style.

struct SelfHealingBannerView: View {
    let banner: SelfHealingBanner

    private var accent: Color { banner.severity == "critical" ? NerVyx.sell : NerVyx.warning }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: "exclamationmark.shield.fill")
                    .font(.system(size: 18))
                    .foregroundStyle(accent)
                Text(banner.severity == "critical" ? "SERVICE DOWN" : "DEGRADED")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(accent)
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .overlay(Capsule().stroke(accent.opacity(0.5), lineWidth: 1))
                Spacer()
            }
            Text(banner.message)
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            if !banner.services.isEmpty {
                FlowChips(services: banner.services, accent: accent)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(accent.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(accent.opacity(0.3), lineWidth: 1))
        .accessibilityIdentifier("self-healing-banner")
    }

    private struct FlowChips: View {
        let services: [SelfHealingService]
        let accent: Color
        var body: some View {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 6)], alignment: .leading, spacing: 6) {
                ForEach(services) { svc in
                    Text("\(svc.name ?? "?") · \(svc.action ?? svc.active_state ?? "")")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(NerVyx.textPrimary)
                        .lineLimit(1)
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .overlay(RoundedRectangle(cornerRadius: 6).stroke(accent.opacity(0.4), lineWidth: 1))
                        .accessibilityIdentifier("self-healing-down-\(svc.name ?? "unknown")")
                }
            }
        }
    }
}
