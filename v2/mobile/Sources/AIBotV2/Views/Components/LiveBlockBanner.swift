import SwiftUI

/// Persistent banner shown on all trading surfaces to confirm live trading is blocked.
struct LiveBlockBanner: View {
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "lock.shield.fill")
                .foregroundStyle(.white)
            Text("LIVE TRADING BLOCKED — PAPER MODE ONLY")
                .font(.caption.weight(.bold))
                .foregroundStyle(.white)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .background(Color(red: 0.8, green: 0.2, blue: 0.2))
    }
}
