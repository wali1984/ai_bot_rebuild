import SwiftUI

// MARK: - Markets (placeholder — screen agent replaces this body)
//
// Data contract (already wired by Infra):
//   GET APIEndpoints.marketOverview (/api/v2/market/overview, ~10.5KB)
//   -> MarketOverviewResponse.data.tickers: [MarketTicker]
//   Stream via APIEndpoints.wsResourceURL(baseURL:path:) + decodeMobileResourceSnapshot,
//   surface envelope truth through StalenessChip. PnL/24h-change colors via
//   NerVyx.pnlColor; single non-semantic series = NerVyx.signal.

struct MarketsView: View {
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    VStack(spacing: 10) {
                        SectionHeader(title: "Markets", accent: NerVyx.signal)
                        HStack {
                            Image(systemName: "chart.bar.xaxis")
                                .font(.system(size: 28))
                                .foregroundStyle(NerVyx.signal)
                            VStack(alignment: .leading, spacing: 3) {
                                Text("Markets screen coming online")
                                    .font(.system(size: 14, weight: .semibold))
                                    .foregroundStyle(NerVyx.textPrimary)
                                Text("Per-symbol tickers, provider coverage and ingestor coverage from /api/v2/market/overview")
                                    .font(.system(size: 11))
                                    .foregroundStyle(NerVyx.textMuted)
                            }
                            Spacer()
                        }
                    }
                    .nerVyxGlassCard(accent: NerVyx.signal)
                }
                .padding(16)
            }
            .nerVyxScreen()
            .navigationTitle("MARKETS")
            .navigationBarTitleDisplayMode(.large)
        }
    }
}
