import SwiftUI

struct WatchDashboardView: View {
    @EnvironmentObject private var watchState: WatchAppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                // Header
                HStack {
                    Image(systemName: "cpu.fill")
                        .foregroundStyle(.blue)
                    Text("NERVYX ONE")
                        .font(.headline)
                        .minimumScaleFactor(0.8)
                }

                // Status dot
                if let d = watchState.dashboard {
                    statusRow(d)
                    pnlRow(d)
                    positionsRow(d)
                    loopRow(d)
                } else {
                    noDataRow
                }

                // Blocked badge
                HStack {
                    Image(systemName: "lock.fill").foregroundStyle(.red).font(.caption)
                    Text("EXECUTION RESTRICTED").font(.caption2.weight(.bold)).foregroundStyle(.yellow)
                }
            }
            .padding(.horizontal, 4)
        }
        .navigationTitle("Dashboard")
    }

    private func statusRow(_ d: WatchDashboardData) -> some View {
        HStack(spacing: 6) {
            Circle()
                .fill(watchColor(d.statusColor))
                .frame(width: 8, height: 8)
            Text(d.overallStatus.capitalized)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            if d.trainerActive {
                Image(systemName: "brain").foregroundStyle(.green).font(.caption2)
            }
        }
    }

    private func pnlRow(_ d: WatchDashboardData) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Total PnL")
                .font(.caption2).foregroundStyle(.secondary)
            Text(String(format: "$%.2f", d.totalPnL))
                .font(.title3.weight(.bold))
                .foregroundStyle(watchColor(d.pnlColor))
            HStack(spacing: 8) {
                Text("R: \(String(format: "$%.2f", d.realizedPnL))")
                    .font(.caption2).foregroundStyle(.secondary)
                Text("U: \(String(format: "$%.2f", d.unrealizedPnL))")
                    .font(.caption2).foregroundStyle(.secondary)
            }
        }
    }

    private func positionsRow(_ d: WatchDashboardData) -> some View {
        HStack {
            Image(systemName: "chart.line.uptrend.xyaxis").foregroundStyle(.blue).font(.caption)
            Text("Positions: \(d.openPositions)")
                .font(.caption)
        }
    }

    private func loopRow(_ d: WatchDashboardData) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Runtime Loop")
                .font(.caption2).foregroundStyle(.secondary)
            HStack(spacing: 8) {
                Label("\(d.intentsAccepted)", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green).font(.caption)
                Label("\(d.intentsBlocked)", systemImage: "xmark.circle.fill")
                    .foregroundStyle(.red).font(.caption)
            }
        }
    }

    private var noDataRow: some View {
        VStack(spacing: 4) {
            if watchState.isConnectedToPhone {
                ProgressView().scaleEffect(0.7)
                Text("Loading...").font(.caption2).foregroundStyle(.secondary)
            } else {
                Image(systemName: "iphone.slash").foregroundStyle(.secondary)
                Text("Phone disconnected").font(.caption2).foregroundStyle(.secondary)
            }
        }
    }

    private func watchColor(_ c: WatchColor) -> Color {
        switch c { case .green: return .green; case .yellow: return .yellow; case .red: return .red; case .orange: return .orange; case .blue: return .blue }
    }
}
