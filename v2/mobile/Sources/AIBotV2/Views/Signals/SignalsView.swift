import SwiftUI

struct SignalsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = SignalsViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                content
            }
            .navigationTitle("NERVYX SENSE")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    actionableToggle
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    } label: {
                        Image(systemName: "arrow.clockwise").foregroundStyle(NerVyx.signal)
                    }
                }
            }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    private var actionableToggle: some View {
        Button {
            vm.actionableOnly.toggle()
        } label: {
            HStack(spacing: 4) {
                Image(systemName: vm.actionableOnly ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(vm.actionableOnly ? NerVyx.signal : NerVyx.textMuted)
                Text("Actionable")
                    .font(.system(size: 13))
                    .foregroundStyle(vm.actionableOnly ? NerVyx.signal : NerVyx.textMuted)
            }
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var content: some View {
        if vm.isLoading && vm.signals.isEmpty {
            VStack(spacing: 16) {
                ProgressView().tint(NerVyx.primary)
                Text("Connecting signal stream…")
                    .font(.system(size: 14))
                    .foregroundStyle(NerVyx.textMuted)
            }
        } else if let err = vm.error, vm.signals.isEmpty {
            VStack(spacing: 16) {
                Image(systemName: "antenna.radiowaves.left.and.right.slash")
                    .font(.system(size: 36))
                    .foregroundStyle(NerVyx.warning)
                Text(err)
                    .font(.system(size: 14))
                    .foregroundStyle(NerVyx.textSecondary)
                    .multilineTextAlignment(.center)
                Button("Retry") { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }
                    .foregroundStyle(NerVyx.signal)
            }
            .padding(32)
        } else if vm.signals.isEmpty {
            VStack(spacing: 12) {
                Image(systemName: "antenna.radiowaves.left.and.right.slash")
                    .font(.system(size: 36))
                    .foregroundStyle(NerVyx.textMuted)
                Text(vm.actionableOnly ? "No actionable signals right now" : "No signals in the current stream")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(NerVyx.textSecondary)
                Text("The trainer is running in INFERENCE_ONLY mode.\nSignals publish continuously as data is processed.")
                    .font(.system(size: 13))
                    .foregroundStyle(NerVyx.textMuted)
                    .multilineTextAlignment(.center)
            }
            .padding(32)
        } else {
            signalsList
        }
    }

    private var signalsList: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                RuntimeTruthLiveCard(title: "Runtime Truth")
                    .padding(.horizontal, 16)
                    .padding(.top, 10)

                // Header row
                HStack {
                    Text("\(vm.signals.count) signals")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.5)
                    Spacer()
                    if vm.actionableOnly {
                        NerVyxBadge(text: "ACTIONABLE ONLY", color: NerVyx.signal, small: true)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)

                VStack(spacing: 0) {
                    ForEach(vm.signals) { sig in
                        NavigationLink(destination: SignalDetailView(signal: sig)) {
                            SignalRowView(signal: sig)
                        }
                        .buttonStyle(.plain)
                        NerVyxDivider().padding(.horizontal, 16)
                    }
                }
            }
            .padding(.bottom, 24)
        }
    }
}

// MARK: - Signal Row

struct SignalRowView: View {
    let signal: MobileSignal

    var body: some View {
        HStack(spacing: 12) {
            // Action indicator
            RoundedRectangle(cornerRadius: 3)
                .fill(NerVyx.actionColor(signal.action))
                .frame(width: 4, height: 44)

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 8) {
                    Text(signal.shortSymbol)
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(NerVyx.textPrimary)
                    Text(signal.timeframe)
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                    Spacer()
                    NerVyxBadge(
                        text: signal.action.uppercased(),
                        color: NerVyx.actionColor(signal.action)
                    )
                }
                HStack(spacing: 8) {
                    ConfidenceBar(value: signal.confidence)
                        .frame(width: 80)
                    Text(signal.confidencePct)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.confidenceColor(signal.confidence))
                    Spacer()
                    if signal.actionable {
                        HStack(spacing: 3) {
                            Image(systemName: "checkmark.circle.fill")
                                .font(.system(size: 10))
                                .foregroundStyle(NerVyx.validation)
                            Text("actionable")
                                .font(.system(size: 10))
                                .foregroundStyle(NerVyx.validation)
                        }
                    } else {
                        Text(signal.shortFillStatus)
                            .font(.system(size: 10))
                            .foregroundStyle(NerVyx.textMuted)
                            .lineLimit(1)
                    }
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(NerVyx.bg)
        .contentShape(Rectangle())
    }
}

// MARK: - Signal Detail

struct SignalDetailView: View {
    let signal: MobileSignal

    var body: some View {
        ZStack {
            NerVyx.bg.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 12) {
                    // Header card
                    VStack(spacing: 12) {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(signal.shortSymbol)
                                    .font(.system(size: 28, weight: .bold))
                                    .foregroundStyle(NerVyx.textPrimary)
                                Text(signal.symbol + " · " + signal.timeframe)
                                    .font(.system(size: 13))
                                    .foregroundStyle(NerVyx.textMuted)
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 6) {
                                NerVyxBadge(
                                    text: signal.action.uppercased(),
                                    color: NerVyx.actionColor(signal.action)
                                )
                                if let price = signal.last_price, price > 0 {
                                    Text(String(format: "$%.4f", price))
                                        .font(.system(size: 13, design: .monospaced))
                                        .foregroundStyle(NerVyx.textSecondary)
                                }
                            }
                        }
                        VStack(spacing: 4) {
                            HStack {
                                Text("Confidence")
                                    .font(.system(size: 12))
                                    .foregroundStyle(NerVyx.textMuted)
                                Spacer()
                                Text(signal.confidencePct)
                                    .font(.system(size: 14, weight: .bold, design: .monospaced))
                                    .foregroundStyle(NerVyx.confidenceColor(signal.confidence))
                            }
                            ConfidenceBar(value: signal.confidence)
                        }
                    }
                    .nerVyxElevatedCard(accent: NerVyx.actionColor(signal.action))

                    // Status card
                    VStack(spacing: 10) {
                        SectionHeader(title: "Execution Status", accent: NerVyx.signal)
                        DataRow(
                            label: "Actionable",
                            value: signal.actionable ? "YES" : "NO",
                            valueColor: signal.actionable ? NerVyx.validation : NerVyx.warning
                        )
                        DataRow(label: "Risk State", value: signal.risk_state)
                        DataRow(label: "Fill Status", value: signal.shortFillStatus, valueColor: NerVyx.textSecondary)
                        if let coverage = signal.data_coverage {
                            DataRow(
                                label: "Data Coverage",
                                value: String(format: "%.1f%%", coverage),
                                valueColor: coverage > 80 ? NerVyx.validation : NerVyx.warning
                            )
                        }
                        if let move = signal.expected_move_bps {
                            DataRow(
                                label: "Expected Move",
                                value: String(format: "%+.2f%%", move / 100.0),
                                valueColor: NerVyx.textSecondary,
                                mono: true
                            )
                        }
                    }
                    .nerVyxCard()

                    // Meta card
                    VStack(spacing: 10) {
                        SectionHeader(title: "Signal Meta", accent: NerVyx.textMuted)
                        DataRow(label: "Signal ID", value: String(signal.id.prefix(20)) + "…", mono: true)
                        DataRow(label: "Published", value: signal.published_at, mono: true)
                    }
                    .nerVyxCard(accent: NerVyx.borderSubtle)
                }
                .padding(16)
                .padding(.bottom, 24)
            }
        }
        .navigationTitle(signal.shortSymbol)
        .navigationBarTitleDisplayMode(.inline)
    }
}
