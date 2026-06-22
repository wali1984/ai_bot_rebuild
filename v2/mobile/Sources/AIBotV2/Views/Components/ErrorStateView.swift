import SwiftUI

struct ErrorStateView: View {
    let message: String
    var retryAction: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 32))
                .foregroundStyle(NerVyx.warning)
            Text("Failed to load data")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(NerVyx.textPrimary)
            Text(message)
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textMuted)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
            if let retry = retryAction {
                Button("Retry", action: retry)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(NerVyx.signal)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
    }
}

struct LoadingView: View {
    var message: String = "Loading…"
    var body: some View {
        VStack(spacing: 12) {
            ProgressView().tint(NerVyx.primary)
            Text(message)
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textMuted)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
