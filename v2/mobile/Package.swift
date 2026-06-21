// swift-tools-version: 5.9
// AIBotV2 — iOS / iPadOS / watchOS native app + Linux CLI
//
// Targets built on Linux:   AIBotV2Core, aibot (CLI)
// Targets built on macOS:   AIBotV2 (iOS app), AIBotV2Watch (watchOS), AIBotV2Core, aibot
// Targets built on iOS:     AIBotV2, AIBotV2Core
// Targets built on watchOS: AIBotV2Watch

import PackageDescription

let package = Package(
    name: "AIBotV2",
    platforms: [
        .macOS(.v13),
        .iOS(.v17),
        .watchOS(.v10),
    ],
    products: [
        // CLI tool — builds on Linux & macOS
        .executable(name: "aibot", targets: ["AIBotV2CLI"]),
        // Cross-platform networking + models library
        .library(name: "AIBotV2Core", targets: ["AIBotV2Core"]),
        // iOS/iPadOS SwiftUI app — Xcode discovers this scheme for archiving
        .library(name: "AIBotV2App", targets: ["AIBotV2"]),
        // watchOS app — Xcode discovers this scheme
        .library(name: "AIBotV2WatchApp", targets: ["AIBotV2Watch"]),
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

        // ── iOS / iPadOS SwiftUI app (Xcode on macOS only) ───────────────
        .target(
            name: "AIBotV2",
            dependencies: ["AIBotV2Core"],
            path: "Sources/AIBotV2"
        ),

        // ── watchOS SwiftUI app (Xcode on macOS only) ────────────────────
        .target(
            name: "AIBotV2Watch",
            dependencies: [],
            path: "Sources/AIBotV2Watch"
        ),

        // ── Tests ─────────────────────────────────────────────────────────
        .testTarget(
            name: "AIBotV2Tests",
            dependencies: ["AIBotV2Core"],
            path: "Tests/AIBotV2Tests"
        ),
    ]
)
