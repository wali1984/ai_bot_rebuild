// swift-tools-version: 5.9
// AIBotV2 — iOS / iPadOS / watchOS native app + Linux CLI
//
// Targets:
//   AIBotV2Core  — platform-agnostic models + networking (builds on Linux)
//   aibot        — Linux/macOS CLI status tool (builds on Linux)
//   AIBotV2      — iOS/iPadOS SwiftUI app (requires Xcode on macOS)
//   AIBotV2Watch — watchOS SwiftUI app (requires Xcode on macOS)

import PackageDescription

let package = Package(
    name: "AIBotV2",
    platforms: [
        .macOS(.v13),
        .iOS(.v17),
        .watchOS(.v10),
    ],
    products: [
        .executable(name: "aibot", targets: ["AIBotV2CLI"]),
        .library(name: "AIBotV2Core", targets: ["AIBotV2Core"]),
    ],
    dependencies: [],
    targets: [

        // ── Cross-platform core (Linux + macOS + iOS + watchOS) ───────────
        .target(
            name: "AIBotV2Core",
            path: "Sources/AIBotV2Core",
            swiftSettings: [
                .enableExperimentalFeature("StrictConcurrency"),
            ]
        ),

        // ── Linux / macOS CLI tool ────────────────────────────────────────
        .executableTarget(
            name: "AIBotV2CLI",
            dependencies: ["AIBotV2Core"],
            path: "Sources/AIBotV2CLI"
        ),

        // ── Tests ─────────────────────────────────────────────────────────
        .testTarget(
            name: "AIBotV2Tests",
            dependencies: ["AIBotV2Core"],
            path: "Tests/AIBotV2Tests"
        ),
    ]
)
