import SwiftUI

struct StatusBadge: View {
    let label: String
    let color: Color

    var body: some View {
        Text(label)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .background(color.opacity(0.2))
            .foregroundStyle(color)
            .clipShape(Capsule())
            .overlay(Capsule().strokeBorder(color.opacity(0.4), lineWidth: 1))
    }
}

extension StatusBadge {
    static func pnl(_ value: Double) -> StatusBadge {
        let label = value >= 0 ? "+$\(String(format: "%.2f", value))" : "-$\(String(format: "%.2f", abs(value)))"
        return StatusBadge(label: label, color: value >= 0 ? .green : .red)
    }
}
