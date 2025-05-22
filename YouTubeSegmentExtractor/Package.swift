// swift-tools-version: 5.10
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "YouTubeSegmentExtractor",
        dependencies: [
    .package(url: "https://github.com/MacPaw/OpenAI.git", from: "0.2.4")
],
    targets: [
        // Targets are the basic building blocks of a package, defining a module or a test suite.
        // Targets can depend on other targets in this package and products from dependencies.
        .executableTarget(
            name: "YouTubeSegmentExtractor"),
    ]
)
