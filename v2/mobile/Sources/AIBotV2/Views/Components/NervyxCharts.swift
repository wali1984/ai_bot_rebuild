import SwiftUI

// MARK: - NerVyx chart primitives
// Dependency-free Path-based charts so every metric can be shown visually
// (sparklines, ring gauges, mini bars) on iOS/iPadOS without Swift Charts.

/// Smooth line sparkline with optional gradient fill under the curve.
struct Sparkline: View {
    let values: [Double]
    var color: Color = NerVyx.signal
    var fill: Bool = true
    var lineWidth: CGFloat = 2

    var body: some View {
        GeometryReader { geo in
            let points = normalizedPoints(in: geo.size)
            ZStack {
                if fill, points.count > 1 {
                    fillPath(points: points, size: geo.size)
                        .fill(
                            LinearGradient(
                                colors: [color.opacity(0.28), color.opacity(0.02)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                }
                if points.count > 1 {
                    linePath(points: points)
                        .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round, lineJoin: .round))
                }
                if let last = points.last {
                    Circle()
                        .fill(color)
                        .frame(width: 5, height: 5)
                        .position(last)
                }
            }
        }
    }

    private func normalizedPoints(in size: CGSize) -> [CGPoint] {
        guard values.count > 1 else { return [] }
        let minValue = values.min() ?? 0
        let maxValue = values.max() ?? 1
        let span = maxValue - minValue
        let inset: CGFloat = 4
        let width = max(size.width - inset * 2, 1)
        let height = max(size.height - inset * 2, 1)
        return values.enumerated().map { index, value in
            let x = inset + width * CGFloat(index) / CGFloat(values.count - 1)
            let normalized = span > 0 ? (value - minValue) / span : 0.5
            let y = inset + height * (1 - CGFloat(normalized))
            return CGPoint(x: x, y: y)
        }
    }

    private func linePath(points: [CGPoint]) -> Path {
        var path = Path()
        guard let first = points.first else { return path }
        path.move(to: first)
        for point in points.dropFirst() {
            path.addLine(to: point)
        }
        return path
    }

    private func fillPath(points: [CGPoint], size: CGSize) -> Path {
        var path = linePath(points: points)
        guard let last = points.last, let first = points.first else { return path }
        path.addLine(to: CGPoint(x: last.x, y: size.height))
        path.addLine(to: CGPoint(x: first.x, y: size.height))
        path.closeSubpath()
        return path
    }
}

/// Circular progress gauge with a center value label.
struct RingGauge: View {
    let value: Double        // 0...1
    let label: String
    let centerText: String
    var color: Color = NerVyx.signal
    var size: CGFloat = 82
    var lineWidth: CGFloat = 7

    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                Circle()
                    .stroke(NerVyx.borderSubtle, lineWidth: lineWidth)
                Circle()
                    .trim(from: 0, to: CGFloat(min(max(value, 0), 1)))
                    .stroke(
                        AngularGradient(
                            colors: [color.opacity(0.55), color],
                            center: .center,
                            startAngle: .degrees(-90),
                            endAngle: .degrees(270)
                        ),
                        style: StrokeStyle(lineWidth: lineWidth, lineCap: .round)
                    )
                    .rotationEffect(.degrees(-90))
                Text(centerText)
                    .font(.system(size: size * 0.22, weight: .bold, design: .monospaced))
                    .foregroundStyle(NerVyx.textPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
                    .padding(.horizontal, 6)
            }
            .frame(width: size, height: size)
            Text(label)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(NerVyx.textMuted)
                .tracking(0.6)
        }
    }
}

/// Compact vertical bar chart for small category counts (e.g. accepted vs blocked).
struct MiniBarChart: View {
    struct Entry: Identifiable {
        let id = UUID()
        let label: String
        let value: Double
        let color: Color
    }

    let entries: [Entry]
    var height: CGFloat = 72

    var body: some View {
        let maxValue = max(entries.map(\.value).max() ?? 1, 1)
        HStack(alignment: .bottom, spacing: 14) {
            ForEach(entries) { entry in
                VStack(spacing: 4) {
                    Text(entry.value.formatted(.number.precision(.fractionLength(0))))
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundStyle(entry.color)
                    RoundedRectangle(cornerRadius: 3)
                        .fill(entry.color.opacity(0.85))
                        .frame(height: max(CGFloat(entry.value / maxValue) * height, 3))
                    Text(entry.label)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .lineLimit(1)
                }
                .frame(maxWidth: .infinity)
            }
        }
    }
}

/// Donut / composition chart (win-loss, direction) with a centre label + legend.
struct DonutChart: View {
    struct Slice: Identifiable {
        let id = UUID()
        let label: String
        let value: Double
        let color: Color
    }

    let slices: [DonutChart.Slice]
    var centerText: String = ""
    var centerLabel: String = ""
    var size: CGFloat = 96
    var lineWidth: CGFloat = 14

    private var total: Double { max(slices.map(\.value).reduce(0, +), 0.0001) }

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                ForEach(Array(sliceAngles.enumerated()), id: \.offset) { _, item in
                    Circle()
                        .trim(from: item.start, to: item.end)
                        .stroke(item.color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .butt))
                        .rotationEffect(.degrees(-90))
                        .padding(lineWidth / 2)
                }
                VStack(spacing: 1) {
                    Text(centerText)
                        .font(.system(size: size * 0.2, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.textPrimary)
                        .lineLimit(1).minimumScaleFactor(0.5)
                    if !centerLabel.isEmpty {
                        Text(centerLabel)
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(NerVyx.textMuted)
                            .tracking(0.5)
                    }
                }
            }
            .frame(width: size, height: size)
            HStack(spacing: 10) {
                ForEach(slices) { slice in
                    HStack(spacing: 4) {
                        RoundedRectangle(cornerRadius: 2).fill(slice.color).frame(width: 8, height: 8)
                        Text("\(slice.label) \(Int((slice.value / total) * 100))%")
                            .font(.system(size: 9, weight: .medium, design: .monospaced))
                            .foregroundStyle(NerVyx.textSecondary)
                    }
                }
            }
        }
    }

    private var sliceAngles: [(start: CGFloat, end: CGFloat, color: Color)] {
        var acc: CGFloat = 0
        return slices.map { slice in
            let frac = CGFloat(slice.value / total)
            let start = acc
            acc += frac
            return (start, acc, slice.color)
        }
    }
}

/// Diverging vertical bars coloured by sign — per-trade PnL, funding, etc.
struct DivergingBars: View {
    let values: [Double]
    var posColor: Color = NerVyx.buy
    var negColor: Color = NerVyx.sell
    var height: CGFloat = 90

    var body: some View {
        let maxAbs = max(values.map { abs($0) }.max() ?? 1, 0.0001)
        HStack(alignment: .center, spacing: 3) {
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                let frac = CGFloat(abs(value) / maxAbs)
                VStack(spacing: 0) {
                    ZStack(alignment: .bottom) {
                        Color.clear.frame(height: height / 2)
                        if value >= 0 {
                            RoundedRectangle(cornerRadius: 2).fill(posColor).frame(height: max(frac * (height / 2), 2))
                        }
                    }
                    Rectangle().fill(NerVyx.borderSubtle).frame(height: 1)
                    ZStack(alignment: .top) {
                        Color.clear.frame(height: height / 2)
                        if value < 0 {
                            RoundedRectangle(cornerRadius: 2).fill(negColor).frame(height: max(frac * (height / 2), 2))
                        }
                    }
                }
                .frame(maxWidth: .infinity)
            }
        }
        .frame(height: height)
    }
}

/// Rolling numeric series recorder for client-side sparkline history.
struct RollingSeries {
    private(set) var values: [Double] = []
    let capacity: Int

    init(capacity: Int = 60) {
        self.capacity = capacity
    }

    mutating func append(_ value: Double) {
        if let last = values.last, last == value { return }
        values.append(value)
        if values.count > capacity {
            values.removeFirst(values.count - capacity)
        }
    }
}
