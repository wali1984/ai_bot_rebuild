import SwiftUI

@main
struct AIBotV2App: App {

    @State private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
                .environment(appState.auth)
        }
    }
}
