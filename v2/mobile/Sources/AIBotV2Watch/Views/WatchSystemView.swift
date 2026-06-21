import SwiftUI

struct WatchSystemView: View {
    @EnvironmentObject private var watchState: WatchAppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                // Connection status
                HStack(spacing: 6) {
                    Circle()
                        .fill(watchState.isConnectedToPhone ? Color.green : Color.red)
                        .frame(width: 8, height: 8)
                    Text(watchState.isConnectedToPhone ? "Phone connected" : "Phone offline")
                        .font(.caption2).foregroundStyle(.secondary)
                }

                if let d = watchState.dashboard {
                    // Trainer status
                    HStack(spacing: 6) {
                        Image(systemName: d.trainerActive ? "brain.fill" : "brain")
                            .foregroundStyle(d.trainerActive ? .green : .secondary)
                            .font(.caption)
                        Text(d.trainerActive ? "Trainer active" : "Trainer inactive")
                            .font(.caption2)
                    }

                    // GPU
                    VStack(alignment: .leading, spacing: 2) {
                        Text("GPU Util").font(.caption2).foregroundStyle(.secondary)
                        HStack(spacing: 4) {
                            GeometryReader { geo in
                                ZStack(alignment: .leading) {
                                    Capsule().fill(Color.secondary.opacity(0.3))
                                    Capsule()
                                        .fill(d.gpuUtilization > 90 ? Color.orange : Color.blue)
                                        .frame(width: geo.size.width * min(d.gpuUtilization / 100, 1.0))
                                }
                                .frame(height: 5)
                            }
                            .frame(height: 5)
                            Text("\(Int(d.gpuUtilization))%")
                                .font(.caption2)
                                .frame(width: 30, alignment: .trailing)
                        }
                    }

                    // Signals
                    HStack(spacing: 6) {
                        Image(systemName: "antenna.radiowaves.left.and.right")
                            .font(.caption).foregroundStyle(.secondary)
                        Text("Signals: \(d.signalsSeen)")
                            .font(.caption2)
                    }

                    // Last updated
                    if let lu = watchState.lastUpdated {
                        Text("Updated: \(lu, style: .relative)")
                            .font(.caption2).foregroundStyle(.tertiary)
                    }
                } else {
                    Text("Waiting for data...")
                        .font(.caption2).foregroundStyle(.secondary)
                }

                // Refresh button
                Button(action: { watchState.requestRefresh() }) {
                    Label("Refresh", systemImage: "arrow.clockwise")
                        .font(.caption.weight(.semibold))
                }
                .buttonStyle(.bordered)
                .tint(.blue)
            }
            .padding(.horizontal, 4)
        }
        .navigationTitle("System")
    }
}
