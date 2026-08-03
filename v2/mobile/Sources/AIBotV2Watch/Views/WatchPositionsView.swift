import SwiftUI

struct WatchPositionsView: View {
    @EnvironmentObject private var watchState: WatchAppState

    var body: some View {
        Group {
            if watchState.positions.isEmpty {
                VStack(spacing: 6) {
                    Image(systemName: "chart.line.downtrend.xyaxis")
                        .foregroundStyle(.secondary)
                    Text("No positions")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } else {
                List(watchState.positions) { pos in
                    watchPositionRow(pos)
                        .listRowBackground(Color.clear)
                }
                .listStyle(.plain)
            }
        }
        .navigationTitle("Positions")
    }

    private func watchPositionRow(_ pos: WatchPosition) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(pos.symbol)
                    .font(.caption.weight(.semibold))
                    .minimumScaleFactor(0.7)
                Spacer()
                Text(pos.side.uppercased())
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(pos.isBuy ? .green : .red)
            }
            HStack {
                Text("PnL:")
                    .font(.caption2).foregroundStyle(.secondary)
                Text(pos.unrealizedPnL.map { String(format: "$%.2f", $0) } ?? "Unavailable")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle((pos.unrealizedPnL ?? 0) >= 0 ? .green : .red)
            }
            HStack {
                Text("Mark:")
                    .font(.caption2).foregroundStyle(.secondary)
                Text(pos.markPrice.map { String(format: "%.4f", $0) } ?? "Unavailable")
                    .font(.caption2)
                    .foregroundStyle(pos.markPriceStale ? .yellow : .secondary)
            }
            if !pos.reason.isEmpty {
                Text(pos.reason)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 2)
    }
}
