import SwiftUI

@main
struct AIBotV2App: App {

    @State private var appState = AppState()
    @State private var nervyxThemeManager = NervyxThemeManager()

    init() {
        configureAppearance()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
                .environment(appState.auth)
                .environment(nervyxThemeManager)
                .preferredColorScheme(.dark)
        }
    }

    private func configureAppearance() {
        // Navigation bar — NerVyx dark
        let navAppearance = UINavigationBarAppearance()
        navAppearance.configureWithOpaqueBackground()
        navAppearance.backgroundColor = UIColor(red: 0.027, green: 0.039, blue: 0.071, alpha: 1) // #070A12
        navAppearance.titleTextAttributes = [
            .foregroundColor: UIColor(red: 0.965, green: 0.969, blue: 0.984, alpha: 1)  // #F6F7FB
        ]
        navAppearance.largeTitleTextAttributes = [
            .foregroundColor: UIColor(red: 0.965, green: 0.969, blue: 0.984, alpha: 1),
            .font: UIFont.systemFont(ofSize: 32, weight: .bold)
        ]
        let backImage = UIImage(systemName: "chevron.left")
        navAppearance.setBackIndicatorImage(backImage, transitionMaskImage: backImage)
        navAppearance.backButtonAppearance.normal.titleTextAttributes = [
            .foregroundColor: UIColor(red: 0.133, green: 0.827, blue: 0.773, alpha: 1) // NerVyx.signal teal
        ]
        UINavigationBar.appearance().standardAppearance = navAppearance
        UINavigationBar.appearance().scrollEdgeAppearance = navAppearance
        UINavigationBar.appearance().compactAppearance = navAppearance
        UINavigationBar.appearance().tintColor = UIColor(red: 0.133, green: 0.827, blue: 0.773, alpha: 1)

        // Tab bar — NerVyx dark
        let tabAppearance = UITabBarAppearance()
        tabAppearance.configureWithOpaqueBackground()
        tabAppearance.backgroundColor = UIColor(red: 0.027, green: 0.039, blue: 0.071, alpha: 1)
        let tealSelected = UIColor(red: 0.133, green: 0.827, blue: 0.773, alpha: 1)
        let mutedNormal = UIColor(red: 0.58, green: 0.64, blue: 0.72, alpha: 1)
        let itemAppearance = UITabBarItemAppearance()
        itemAppearance.normal.iconColor = mutedNormal
        itemAppearance.normal.titleTextAttributes = [.foregroundColor: mutedNormal]
        itemAppearance.selected.iconColor = tealSelected
        itemAppearance.selected.titleTextAttributes = [.foregroundColor: tealSelected]
        tabAppearance.stackedLayoutAppearance = itemAppearance
        tabAppearance.inlineLayoutAppearance = itemAppearance
        tabAppearance.compactInlineLayoutAppearance = itemAppearance
        UITabBar.appearance().standardAppearance = tabAppearance
        UITabBar.appearance().scrollEdgeAppearance = tabAppearance
    }
}
