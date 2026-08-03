import SwiftUI

struct MetricRow: View {
    let label: String
    let value: String
    var valueColor: Color = NerVyx.textPrimary
    var systemImage: String? = nil

    var body: some View {
        HStack {
            if let icon = systemImage {
                Image(systemName: icon)
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(width: 18)
            }
            Text(label)
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textMuted)
            Spacer()
            Text(value)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(valueColor)
        }
    }
}

struct MetricCard: View {
    let title: String
    let value: String
    var subtitle: String? = nil
    var valueColor: Color = NerVyx.textPrimary
    var icon: String = "chart.bar"

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 10))
                    .foregroundStyle(NerVyx.textMuted)
                Text(title)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(NerVyx.textMuted)
                    .tracking(0.4)
            }
            Text(value)
                .font(.system(size: 18, weight: .bold, design: .monospaced))
                .foregroundStyle(valueColor)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            if let sub = subtitle {
                Text(sub)
                    .font(.system(size: 10))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(1)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }
}

struct GaugeCard: View {
    let title: String
    let value: Double
    let max: Double
    let unit: String
    var color: Color = NerVyx.inference

    private var fraction: Double { max > 0 ? min(value / max, 1.0) : 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(NerVyx.textMuted)
                .tracking(0.5)
            HStack {
                Text("\(Int(value))\(unit)")
                    .font(.system(size: 18, weight: .bold, design: .monospaced))
                    .foregroundStyle(color)
                Spacer()
                Text("\(Int(fraction * 100))%")
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textMuted)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 3).fill(NerVyx.borderSubtle).frame(height: 5)
                    RoundedRectangle(cornerRadius: 3)
                        .fill(color)
                        .frame(width: geo.size.width * CGFloat(fraction), height: 5)
                }
            }
            .frame(height: 5)
        }
        .padding(12)
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }
}
