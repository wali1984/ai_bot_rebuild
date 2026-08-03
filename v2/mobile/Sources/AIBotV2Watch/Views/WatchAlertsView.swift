import SwiftUI

struct WatchAlertsView: View {
    @EnvironmentObject private var watchState: WatchAppState

    var body: some View {
        Group {
            if watchState.alerts.isEmpty {
                VStack(spacing: 6) {
                    Image(systemName: "bell.slash").foregroundStyle(.secondary)
                    Text("No alerts").font(.caption).foregroundStyle(.secondary)
                }
            } else {
                List(watchState.alerts) { alert in
                    watchAlertRow(alert)
                        .listRowBackground(Color.clear)
                }
                .listStyle(.plain)
            }
        }
        .navigationTitle("Alerts")
    }

    private func watchAlertRow(_ alert: WatchAlert) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 4) {
                Circle()
                    .fill(watchColor(alert.severityColor))
                    .frame(width: 6, height: 6)
                Text(alert.symbol.isEmpty ? alert.type : "[\(alert.symbol)]")
                    .font(.caption.weight(.semibold))
                    .minimumScaleFactor(0.8)
            }
            Text(alert.message)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(.vertical, 2)
    }

    private func watchColor(_ c: WatchColor) -> Color {
        switch c { case .green: return .green; case .yellow: return .yellow; case .red: return .red; case .orange: return .orange; case .blue: return .blue }
    }
}
