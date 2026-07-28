import SwiftUI

struct LoginView: View {

    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState

    @State private var email = ""
    @State private var password = ""
    @State private var serverURL = ""
    @State private var showAdvanced = false
    @FocusState private var focusedField: Field?

    private enum Field { case email, password, server }

    var body: some View {
        ZStack {
            NerVyx.bg.ignoresSafeArea()
            // Subtle radial glow behind logo
            RadialGradient(
                colors: [NerVyx.primary.opacity(0.12), Color.clear],
                center: .top,
                startRadius: 0,
                endRadius: 400
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 32) {
                    header
                    formCard
                    if case .error(let msg) = auth.state {
                        errorBanner(msg)
                    }
                    loginButton
                    advancedSection
                    Spacer(minLength: 40)
                }
                .padding(.horizontal, 24)
                .padding(.top, 60)
            }
        }
        .onAppear { serverURL = appState.baseURL }
    }

    // MARK: - Header

    private var header: some View {
        VStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(NerVyx.primary.opacity(0.15))
                    .frame(width: 88, height: 88)
                Image(NervyxAssets.mark)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 52, height: 52)
            }
            VStack(spacing: 6) {
                Text(NervyxBrand.productName)
                    .font(.system(size: 26, weight: .bold, design: .rounded))
                    .foregroundStyle(NerVyx.textPrimary)
                Text(NervyxBrand.descriptor)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(NerVyx.textMuted)
                HStack(spacing: 6) {
                    LivePulse(color: NerVyx.signal)
                    Text(NervyxBrand.tagline)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(NerVyx.signal)
                        .tracking(0.8)
                }
                .padding(.top, 2)
            }
            NerVyxBadge(text: NervyxBrand.liveBlockedLabel.uppercased(), color: NerVyx.sell)
        }
    }

    // MARK: - Form

    private var formCard: some View {
        VStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("EMAIL")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(NerVyx.textMuted)
                    .tracking(0.8)
                TextField("operator@nervyx.ai", text: $email)
                    .textContentType(.emailAddress)
                    .autocapitalization(.none)
                    .keyboardType(.emailAddress)
                    .focused($focusedField, equals: .email)
                    .submitLabel(.next)
                    .onSubmit { focusedField = .password }
                    .foregroundStyle(NerVyx.textPrimary)
                    .padding(12)
                    .background(NerVyx.panelElevated)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(
                        focusedField == .email ? NerVyx.primary : NerVyx.borderSubtle, lineWidth: 1
                    ))
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("PASSWORD")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(NerVyx.textMuted)
                    .tracking(0.8)
                SecureField("••••••••", text: $password)
                    .textContentType(.password)
                    .focused($focusedField, equals: .password)
                    .submitLabel(.go)
                    .onSubmit { performLogin() }
                    .foregroundStyle(NerVyx.textPrimary)
                    .padding(12)
                    .background(NerVyx.panelElevated)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(
                        focusedField == .password ? NerVyx.primary : NerVyx.borderSubtle, lineWidth: 1
                    ))
            }
        }
        .padding(20)
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }

    private func errorBanner(_ message: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "exclamationmark.circle.fill")
                .foregroundStyle(NerVyx.sell)
            Text(message)
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.sell)
                .lineLimit(2)
        }
        .padding(12)
        .background(NerVyx.sell.opacity(0.1))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(NerVyx.sell.opacity(0.3), lineWidth: 1))
    }

    private var loginButton: some View {
        Button(action: performLogin) {
            Group {
                if case .loading = auth.state {
                    HStack(spacing: 10) {
                        ProgressView().tint(.white)
                        Text("Authenticating…")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.white)
                    }
                } else {
                    Text("Sign In to NERVYX ONE")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(.white)
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 52)
            .background(
                LinearGradient(
                    colors: [NerVyx.primary, Color(hex: "5A3EDB")],
                    startPoint: .leading,
                    endPoint: .trailing
                )
            )
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .disabled(email.isEmpty || password.isEmpty || {
            if case .loading = auth.state { return true }
            return false
        }())
        .opacity(email.isEmpty || password.isEmpty ? 0.5 : 1)
    }

    // MARK: - Advanced

    private var advancedSection: some View {
        VStack(spacing: 0) {
            Button(action: { SwiftUI.withAnimation(.default) { showAdvanced.toggle() } }) {
                HStack(spacing: 6) {
                    Image(systemName: "gearshape")
                        .font(.caption)
                        .foregroundStyle(NerVyx.textMuted)
                    Text("Server Settings")
                        .font(.system(size: 13))
                        .foregroundStyle(NerVyx.textMuted)
                    Spacer()
                    Image(systemName: showAdvanced ? "chevron.up" : "chevron.down")
                        .font(.caption2)
                        .foregroundStyle(NerVyx.textMuted)
                }
            }
            .buttonStyle(.plain)

            if showAdvanced {
                VStack(alignment: .leading, spacing: 8) {
                    NerVyxDivider().padding(.top, 8)
                    Text("BACKEND URL")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.8)
                        .padding(.top, 4)
                    TextField("https://dashboard.wajidali.us", text: $serverURL)
                        .textContentType(.URL)
                        .autocapitalization(.none)
                        .keyboardType(.URL)
                        .focused($focusedField, equals: .server)
                        .foregroundStyle(NerVyx.textPrimary)
                        .font(.system(size: 13, design: .monospaced))
                        .padding(10)
                        .background(NerVyx.panelElevated)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(NerVyx.borderSubtle, lineWidth: 1))
                    Button("Save URL") {
                        appState.setBaseURL(serverURL.isEmpty ? "https://dashboard.wajidali.us" : serverURL)
                    }
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(NerVyx.signal)
                }
            }
        }
        .padding(14)
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }

    // MARK: - Action

    private func performLogin() {
        guard !email.isEmpty, !password.isEmpty else { return }
        Task {
            await auth.login(email: email, password: password, baseURL: appState.baseURL)
        }
    }
}
