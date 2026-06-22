import SwiftUI

@main
struct AIBotV2App: App {

    @State private var appState = AppState()
    @State private var nervyxThemeManager = NervyxThemeManager()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
                .environment(appState.auth)
                .environment(nervyxThemeManager)
        }
    }
}
