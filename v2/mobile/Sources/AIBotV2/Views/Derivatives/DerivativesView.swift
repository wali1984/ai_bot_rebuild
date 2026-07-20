import SwiftUI

// MARK: - Derivatives (placeholder — screen agent replaces this body)
//
// Data contract (already wired by Infra):
//   GET APIEndpoints.mobileDerivativesSummary (/api/v2/mobile/derivatives-summary, ~4.5KB)
//   -> MobileDerivativesSummary (aggregate, global_regime, top_symbols[20] by OI)
//   Full payload (WiFi/detail only): APIEndpoints.derivatives (~102KB).
//   Funding sign colors = NerVyx.buy/sell only; long-vs-short via SplitBar;
//   per-symbol funding via HBarRow. Surface staleness_seconds via StalenessChip.

struct DerivativesView: View {
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    VStack(spacing: 10) {
                        SectionHeader(title: "Derivatives", accent: NerVyx.inference)
                        HStack {
                            Image(systemName: "percent")
                                .font(.system(size: 28))
                                .foregroundStyle(NerVyx.inference)
                            VStack(alignment: .leading, spacing: 3) {
                                Text("Derivatives screen coming online")
                                    .font(.system(size: 14, weight: .semibold))
                                    .foregroundStyle(NerVyx.textPrimary)
                                Text("Open interest, liquidations, funding and long/short from /api/v2/mobile/derivatives-summary")
                                    .font(.system(size: 11))
                                    .foregroundStyle(NerVyx.textMuted)
                            }
                            Spacer()
                        }
                    }
                    .nerVyxGlassCard(accent: NerVyx.inference)
                }
                .padding(16)
            }
            .nerVyxScreen()
            .navigationTitle("DERIVATIVES")
            .navigationBarTitleDisplayMode(.large)
        }
    }
}
