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
        NavigationStack {
            ScrollView {
                VStack(spacing: 28) {
                    header
                    form
                    if case .error(let msg) = auth.state {
                        errorBanner(msg)
                    }
                    loginButton
                    advancedSection
                }
                .padding()
            }
            .navigationTitle("NERVYX ONE")
            .navigationBarTitleDisplayMode(.large)
        }
        .onAppear {
            serverURL = appState.baseURL
        }
    }

    private var header: some View {
        VStack(spacing: 8) {
            Image(NervyxAssets.mark)
                .resizable()
                .scaledToFit()
                .frame(width: 72, height: 72)
                .accessibilityLabel("NERVYX ONE mark")
            Text(NervyxBrand.productName)
                .font(.title2.weight(.semibold))
            Text(NervyxBrand.descriptor)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text(NervyxBrand.tagline)
                .font(.caption.weight(.semibold))
                .foregroundStyle(NervyxColors.signalAccent)
            Text(NervyxBrand.paperStatus)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 20)
    }

    private var form: some View {
        VStack(spacing: 16) {
            TextField("Email", text: $email)
                .textContentType(.emailAddress)
                .autocapitalization(.none)
                .keyboardType(.emailAddress)
                .focused($focusedField, equals: .email)
                .submitLabel(.next)
                .onSubmit { focusedField = .password }
                .textFieldStyle(.roundedBorder)

            SecureField("Password", text: $password)
                .textContentType(.password)
                .focused($focusedField, equals: .password)
                .submitLabel(.go)
                .onSubmit { performLogin() }
                .textFieldStyle(.roundedBorder)
        }
    }

    private func errorBanner(_ message: String) -> some View {
        HStack {
            Image(systemName: "xmark.circle.fill")
            Text(message)
                .font(.caption)
        }
        .foregroundStyle(.red)
        .padding(.vertical, 8)
        .padding(.horizontal, 12)
        .background(Color.red.opacity(0.1))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var loginButton: some View {
        Button(action: performLogin) {
            Group {
                if case .loading = auth.state {
                    ProgressView().tint(.white)
                } else {
                    Text("Sign In")
                        .fontWeight(.semibold)
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 50)
        }
        .buttonStyle(.borderedProminent)
        .disabled(email.isEmpty || password.isEmpty || {
            if case .loading = auth.state { return true }
            return false
        }())
    }

    private var advancedSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(action: { showAdvanced.toggle() }) {
                HStack {
                    Text("Server Settings")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Image(systemName: showAdvanced ? "chevron.up" : "chevron.down")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .buttonStyle(.plain)

            if showAdvanced {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Server URL")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    TextField("https://dashboard.wajidali.us", text: $serverURL)
                        .textContentType(.URL)
                        .autocapitalization(.none)
                        .keyboardType(.URL)
                        .focused($focusedField, equals: .server)
                        .textFieldStyle(.roundedBorder)
                        .font(.caption)
                    Button("Save") {
                        appState.setBaseURL(serverURL.isEmpty ? "https://dashboard.wajidali.us" : serverURL)
                    }
                    .font(.caption)
                    .buttonStyle(.bordered)
                }
                .padding(12)
                .background(Color(.systemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }
        }
    }

    private func performLogin() {
        guard !email.isEmpty, !password.isEmpty else { return }
        Task {
            await auth.login(email: email, password: password, baseURL: appState.baseURL)
        }
    }
}
