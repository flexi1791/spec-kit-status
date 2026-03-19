# Day 4: 81 Commits — The Implementation Explosion

*Part 3 of "10 Days, 400 Commits: Building a Multi-Target iOS 26 App with AI-Driven Spec Development"*

---

81 commits in one day. Not because we were moving fast and breaking things — because the specs made every implementation decision already.

## The Morning Sprint

Day 4 began with nine specs queued for implementation, each with a completed plan and task list. The `/speckit.implement` workflow processes tasks one at a time: read the task, write the code, verify it builds, check it off, move to the next.

Here's what we shipped before lunch:

| Spec | Feature | Key Pattern |
|------|---------|-------------|
| 001 | Core data model + list view | SwiftData `@Model`, `FetchDescriptor`, date-grouped sections |
| 003 | Category management | Predefined categories, toggle model, icon grid picker |
| 004 | Onboarding flow | Multi-page `TabView` with `@AppStorage` completion flag |
| 007 | Detail & edit screen | Shared view for add-and-confirm + view-and-edit modes |
| 009 | App navigation | Tab structure, deep link routing, launch phase state machine |
| 012 | Enrichment pipeline | API lookup → fallback chain → image fetch → status tracking |
| 013 | Manual add input | Add-item sheet with category detection and inline input |
| 016 | Home screen widget | Medium widget via WidgetKit + App Group |
| 019 | Category icons | iTunes API integration for category imagery |

Nine specs. One day. This is what specification-driven development buys you: the AI isn't guessing at architecture or debating patterns. The plan says "create `EnrichmentCoordinator.swift` in `Services/`, inject `NetworkMonitor` and `ItemRepository`, implement a `processNext()` loop that checks network state before each lookup." The AI writes exactly that.

## Pattern: The Background Processing Coordinator

The enrichment pipeline (spec 012) required a coordinator that:
- Processes items one at a time
- Pauses when the network drops
- Resumes when connectivity returns
- Can be paused/resumed manually
- Reports progress to the UI

This is a reusable pattern for any app with background processing:

```swift
// Background processing coordinator with network awareness.
// Processes queued items one at a time, pausing when offline
// and resuming when connectivity returns.

@MainActor
@Observable
final class ProcessingCoordinator {
  var isProcessing = false
  var pendingCount = 0

  private let repository: ItemRepository
  private let networkMonitor: NetworkMonitoring
  private let lookupService: LookupService
  private var processingTask: Task<Void, Never>?

  init(
    repository: ItemRepository,
    networkMonitor: NetworkMonitoring,
    lookupService: LookupService
  ) {
    self.repository = repository
    self.networkMonitor = networkMonitor
    self.lookupService = lookupService
  }

  func startProcessing() {
    guard processingTask == nil else { return }

    isProcessing = true
    processingTask = Task {
      await processQueue()
      isProcessing = false
      processingTask = nil
    }
  }

  func stopProcessing() {
    processingTask?.cancel()
    processingTask = nil
    isProcessing = false
  }

  private func processQueue() async {
    while !Task.isCancelled {
      // Re-fetch pending items each iteration (list may have changed)
      let pending = repository.fetchPending()
      pendingCount = pending.count

      guard let next = pending.first else { break }

      // Wait for network before attempting lookup
      guard networkMonitor.isConnected else {
        // Park here until network returns, checking periodically
        try? await Task.sleep(for: .seconds(5))
        continue
      }

      do {
        let metadata = try await lookupService.lookup(title: next.title)
        repository.applyEnrichment(to: next, from: metadata)
      } catch {
        repository.markFailed(next, error: error)
        #if DEBUG
        print("[ProcessingCoordinator] Enrichment failed for '\(next.title)': \(error)")
        #endif
      }
    }
  }
}
```

Key decisions the spec made for us:
- **`@MainActor @Observable`** — the coordinator is a UI-facing object. It publishes `isProcessing` and `pendingCount` directly to SwiftUI views. No Combine. No delegates.
- **Protocol injection** — `NetworkMonitoring` is a protocol, not the concrete `NetworkMonitor`. This lets us test without real network state.
- **Re-fetch each iteration** — The pending list can change while processing (user adds items, iCloud sync arrives). We don't cache the queue.
- **`#if DEBUG` print** — Constitution Principle IX: constructive errors with diagnostic context.

## Pattern: Bridging NWPathMonitor to @Observable

The coordinator needs network state. Apple's `NWPathMonitor` uses a callback-based API on a `DispatchQueue`. Swift 6.2 strict concurrency doesn't love that. Here's the bridge:

```swift
import Network

// Bridges Apple's callback-based NWPathMonitor to Swift 6.2
// @Observable for direct SwiftUI consumption.

protocol NetworkMonitoring: AnyObject {
  var isConnected: Bool { get }
}

@MainActor
@Observable
final class NetworkMonitor: NetworkMonitoring {
  var isConnected = true

  private let monitor = NWPathMonitor()
  private let queue = DispatchQueue(label: "NetworkMonitor")

  init() {
    monitor.pathUpdateHandler = { [weak self] path in
      Task { @MainActor [weak self] in
        self?.isConnected = path.status == .satisfied
      }
    }
    monitor.start(queue: queue)
  }

  deinit {
    monitor.cancel()
  }
}
```

The pattern is simple but the concurrency annotations are precise:
- `@MainActor` on the class ensures `isConnected` is only mutated on the main thread
- `Task { @MainActor in ... }` marshals the callback from the `DispatchQueue` to the main actor
- `[weak self]` prevents retain cycles through the monitor's closure

This pattern applies to any callback-based Apple API you need to bridge to modern Swift concurrency: `CLLocationManager`, `CBCentralManager`, `WCSession`, etc.

## Pattern: WidgetKit with Shared Data

The widget (spec 016) reads from the same SwiftData store as the app. This requires an App Group container:

```swift
import WidgetKit
import SwiftData

struct ItemWidgetProvider: TimelineProvider {
  func placeholder(in context: Context) -> ItemEntry {
    ItemEntry(date: .now, items: ItemEntry.sampleItems)
  }

  func getSnapshot(in context: Context, completion: @escaping (ItemEntry) -> Void) {
    completion(ItemEntry(date: .now, items: ItemEntry.sampleItems))
  }

  func getTimeline(in context: Context, completion: @escaping (Timeline<ItemEntry>) -> Void) {
    do {
      let container = try SharedContainer.create()
      let context = ModelContext(container)

      var descriptor = FetchDescriptor<SchemaV1.Item>(
        sortBy: [SortDescriptor(\.dateAdded, order: .reverse)]
      )
      descriptor.fetchLimit = 4

      let items = try context.fetch(descriptor)
      let entry = ItemEntry(date: .now, items: items.map { WidgetItem(from: $0) })

      // Refresh every 24 hours — widget data doesn't need real-time updates
      let timeline = Timeline(
        entries: [entry],
        policy: .after(.now.addingTimeInterval(86_400))
      )
      completion(timeline)
    } catch {
      #if DEBUG
      print("[Widget] Failed to fetch items: \(error)")
      #endif
      let entry = ItemEntry(date: .now, items: [])
      completion(Timeline(entries: [entry], policy: .after(.now.addingTimeInterval(3_600))))
    }
  }
}
```

The widget creates its *own* `ModelContainer` via `SharedContainer.create()` — it can't share a container instance with the app (they're separate processes). The App Group ensures they read from the same SQLite file.

## XcodeGen for Multi-Target Management

With four targets (app, widget, watch, share extension) and a Swift Package, managing the `.xcodeproj` by hand would be miserable. We used [XcodeGen](https://github.com/yonaskolb/XcodeGen) with a `project.yml`:

```yaml
name: MyApp
targets:
  MyApp:
    type: application
    platform: iOS
    deploymentTarget: "26.0"
    sources: [MyApp]
    dependencies:
      - package: MyKit
      - target: MyWidget
        embed: true
      - target: ShareExtension
        embed: true

  MyWidget:
    type: app-extension
    platform: iOS
    sources: [MyWidget]
    dependencies:
      - package: MyKit
    entitlements:
      path: MyWidget/MyWidget.entitlements

  ShareExtension:
    type: app-extension
    platform: iOS
    sources: [ShareExtension]
    dependencies:
      - package: MyKit
```

Every time we added a new Swift file, we ran `xcodegen generate` in the `src/` directory. This kept the project file deterministic and merge-conflict-free — critical when you're generating 81 commits in a day.

## Spec Timeline: Day 4

| Time | Action | Why |
|------|--------|-----|
| Morning | Implement specs 001, 003, 004, 007, 009 | Core model, categories, onboarding, detail, navigation |
| Afternoon | Implement specs 012, 013, 016, 019 | Enrichment pipeline, manual input, widgets, icons |
| Evening | Post-implementation clarifications on 4 specs | Implementation revealed edge cases the specs missed |
| Evening | Model relationship refactoring | Spec 001 and 003 needed clearer ownership boundaries |

The evening was revealing. Even with thorough specs, implementation exposed edge cases:
- Spec 001's list view needed selection highlight and auto-scroll (added as FR-012)
- Spec 003's category picker needed to filter to only enabled categories in the add-item flow
- Spec 007's detail view needed to prevent title editing after save (to protect enrichment data)
- The relationship between items and categories needed refactoring from bidirectional to unidirectional

These weren't spec failures — they were the spec process working as designed. Implementation is a form of testing. The clarification amendments kept the specs synchronized with reality.

### New Specs from Implementation

Day 4 also produced three new specs, born from implementation insights:

| New Spec | Why It Emerged |
|----------|----------------|
| 017 — iCloud Sync | Implementing the shared container revealed CloudKit integration was non-trivial enough for its own spec |
| 018 — Siri Intents | The data model was now stable enough to define App Intents entities |
| 019 — Category Icons | Icon fetching from the iTunes API was complex enough to warrant its own resolution service |

**Total specs: 21.**

## The Velocity Math

81 commits ÷ ~12 hours of work = **one commit every 9 minutes**. Each commit was a discrete, buildable step: add a model, add a service, add a view, fix a build error, update a test. The AI wasn't "generating code" — it was executing a task list where every task was pre-validated against the spec.

Could we have done this without specs? Probably. In 3-4 weeks instead of a day, with twice the rework.

---

**Total at end of Day 4:**
- 21 feature specs
- 9 specs fully implemented
- Core data model, enrichment pipeline, widgets, onboarding — all working
- 235 total commits

Next up: [Days 5–6 — Vision OCR, Siri App Intents, and deep linking architecture](/blog/04-vision-siri-deep-links.md).

---

*This is Part 3 of a 7-part series. [Read the series overview](/blog/README.md).*
