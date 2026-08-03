import SwiftUI

struct WatchRootView: View {
    @EnvironmentObject private var watchState: WatchAppState

    var body: some View {
        TabView {
            WatchDashboardView()
                .tag(0)

            WatchPositionsView()
                .tag(1)

            WatchAlertsView()
                .tag(2)

            WatchSystemView()
                .tag(3)
        }
        .tabViewStyle(.page)
        .onAppear { watchState.requestRefresh() }
    }
}
