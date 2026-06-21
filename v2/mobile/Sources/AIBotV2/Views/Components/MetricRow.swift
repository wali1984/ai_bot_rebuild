import SwiftUI

struct MetricRow: View {
    let label: String
    let value: String
    var valueColor: Color = .primary
    var systemImage: String? = nil

    var body: some View {
        HStack {
            if let icon = systemImage {
                Image(systemName: icon)
                    .foregroundStyle(.secondary)
                    .frame(width: 20)
            }
            Text(label)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .foregroundStyle(valueColor)
                .fontWeight(.medium)
        }
        .font(.subheadline)
    }
}

struct MetricCard: View {
    let title: String
    let value: String
    var subtitle: String? = nil
    var valueColor: Color = .primary
    var icon: String = "chart.bar"

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: icon)
                    .foregroundStyle(.secondary)
                Text(title)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text(value)
                .font(.title3.weight(.semibold))
                .foregroundStyle(valueColor)
            if let sub = subtitle {
                Text(sub)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

struct GaugeCard: View {
    let title: String
    let value: Double
    let max: Double
    let unit: String
    var color: Color = .blue

    private var fraction: Double { max > 0 ? min(value / max, 1.0) : 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Text("\(Int(value))\(unit)")
                    .font(.title3.weight(.semibold))
                Spacer()
                Text("\(Int(fraction * 100))%")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(.quaternary)
                    Capsule()
                        .fill(color)
                        .frame(width: geo.size.width * fraction)
                }
                .frame(height: 6)
            }
            .frame(height: 6)
        }
        .padding()
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}
