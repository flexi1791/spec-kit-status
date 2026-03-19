# Days 7–8: iCloud Sync, Deduplication, and Offline Resilience

*Part 5 of "10 Days, 400 Commits: Building a Multi-Target iOS 26 App with AI-Driven Spec Development"*

---

iCloud sync "just works" — until you have two devices and a share extension all writing to the same container. Here's what we learned about deduplication.

## The Promise and Reality of SwiftData + CloudKit

SwiftData's CloudKit integration is genuinely impressive. Add three lines to your `ModelConfiguration` and your data syncs to iCloud automatically:

```swift
let config = ModelConfiguration(
  schema: schema,
  groupContainer: .identifier("group.com.example.shared"),
  cloudKitDatabase: .private("iCloud.com.example.app")
)
```

That's it. No CKRecord mapping. No zone management. No subscription handling. SwiftData does it all.

**But.**

CloudKit sync is eventually consistent. When two devices create items offline and then sync, CloudKit doesn't merge — it creates both. When the same item is added via the app on one device and via Siri on another, you get two copies. When a share extension creates an item on the same device as the app, the sync round-trip can duplicate it.

Spec 017 (iCloud Sync) predicted this. The clarification session asked: *"What is the deduplication strategy when the same item arrives from multiple sources?"* The answer became our deduplication algorithm.

## Pattern: Reactive Deduplication

The strategy: listen for remote changes via `NSPersistentStoreRemoteChange`, then scan for and merge duplicates.

```swift
// Post-iCloud-sync deduplication.
// Triggered reactively when remote changes arrive, not on a timer.
// Uses external ID as the gold standard for matching, with title
// normalization as fallback.

@MainActor
final class ItemRepository {
  private let context: ModelContext

  init(context: ModelContext) {
    self.context = context

    // Listen for iCloud sync completions
    NotificationCenter.default.addObserver(
      forName: .NSPersistentStoreRemoteChange,
      object: nil,
      queue: .main
    ) { [weak self] _ in
      Task { @MainActor in
        self?.deduplicateAfterSync()
      }
    }
  }

  func deduplicateAfterSync() {
    guard let allItems = try? context.fetch(FetchDescriptor<SchemaV1.Item>()) else { return }

    // Group by external ID (definitive match)
    let byExternalID = Dictionary(grouping: allItems.filter { $0.externalID != nil }) {
      $0.externalID!
    }

    for (_, duplicates) in byExternalID where duplicates.count > 1 {
      mergeDuplicates(duplicates)
    }

    // Secondary pass: group by normalized title + category (fuzzy match)
    let remaining = (try? context.fetch(FetchDescriptor<SchemaV1.Item>())) ?? []
    let byTitleCategory = Dictionary(grouping: remaining) {
      normalizeTitle($0.title) + "|" + ($0.category?.name ?? "")
    }

    for (_, duplicates) in byTitleCategory where duplicates.count > 1 {
      // Only merge if no conflicting external IDs
      let uniqueIDs = Set(duplicates.compactMap(\.externalID))
      guard uniqueIDs.count <= 1 else { continue }
      mergeDuplicates(duplicates)
    }

    try? context.save()
  }

  private func mergeDuplicates(_ duplicates: [SchemaV1.Item]) {
    // Keep the "richest" record — the one with the most metadata
    let sorted = duplicates.sorted { richness($0) > richness($1) }
    let keeper = sorted[0]
    let losers = sorted.dropFirst()

    for loser in losers {
      // Merge any data the keeper is missing
      if keeper.externalID == nil { keeper.externalID = loser.externalID }
      if keeper.imageURL == nil { keeper.imageURL = loser.imageURL }
      if keeper.tags.isEmpty { keeper.tags = loser.tags }
      if keeper.personalNotes.isEmpty { keeper.personalNotes = loser.personalNotes }
      if !keeper.isCompleted { keeper.isCompleted = loser.isCompleted }

      context.delete(loser)
    }
  }

  private func richness(_ item: SchemaV1.Item) -> Int {
    var score = 0
    if item.externalID != nil { score += 4 }
    if item.imageURL != nil { score += 2 }
    if !item.tags.isEmpty { score += 1 }
    if !item.personalNotes.isEmpty { score += 1 }
    return score
  }

  private func normalizeTitle(_ title: String) -> String {
    title
      .lowercased()
      .trimmingCharacters(in: .whitespacesAndNewlines)
      .folding(options: .diacriticInsensitive, locale: .current)
  }
}
```

Key design decisions:
- **Two-pass matching** — First by external ID (definitive), then by normalized title (fuzzy). The fuzzy pass only fires when external IDs don't conflict.
- **Richness scoring** — The record with the most metadata survives. External ID is weighted highest because it enables future enrichment.
- **Merge, don't pick** — The keeper inherits any data the losers have that it's missing. No data is lost.
- **Reactive trigger** — Deduplication runs when `NSPersistentStoreRemoteChange` fires, not on a timer. This ensures it runs immediately after sync completes.

## Pattern: Offline-First Enrichment Queue

The enrichment coordinator from Day 4 handles online processing. But what about items added while offline? Spec 006 (Offline Resilience) defined the queue:

```swift
// Enrichment status tracks where each item is in the pipeline.
// "pending" items are queued for enrichment when network returns.

enum EnrichmentStatus: String, Codable {
  case pending     // Waiting for network or first processing attempt
  case enriched    // Successfully enriched with metadata
  case failed      // Enrichment attempted and failed

  var needsProcessing: Bool {
    self == .pending
  }
}
```

The coordinator's `processQueue()` method (from Day 4) already handles this: it fetches all `.pending` items and processes them one by one. When the network drops, it stops. When the network returns, it resumes.

The `NetworkMonitor` bridge (also from Day 4) drives this reactively:

```swift
// In the app's root view, observe network changes
// and trigger enrichment when connectivity returns.

.onChange(of: networkMonitor.isConnected) { _, isConnected in
  if isConnected {
    coordinator.startProcessing()
  }
}
```

No timers. No polling. No retry loops. The network monitor publishes a state change, the coordinator processes the queue, done.

## Constructive Error Handling

Constitution Principle IX became critical during sync work. iCloud sync failures are opaque — CloudKit gives you `CKError` with a code but rarely enough context to debug. Our rule: **every error must carry diagnostic context**.

```swift
// Constitution Principle IX: Errors carry full context.
// Every catch block logs enough information to diagnose
// the issue without reproducing it.

do {
  try context.save()
} catch {
  #if DEBUG
  print("""
  [ItemRepository] Save failed after deduplication
    Items in context: \(context.insertedModelsArray.count) inserted, \
    \(context.changedModelsArray.count) changed, \
    \(context.deletedModelsArray.count) deleted
    Error: \(error)
  """)
  #endif
  // Re-throw or handle — but never silently swallow
  throw RepositoryError.saveFailed(
    operation: "deduplication",
    itemCount: context.insertedModelsArray.count,
    underlying: error
  )
}
```

The pattern: `#if DEBUG` for verbose console output (development), structured error types for programmatic handling (production). Never `catch { }`. Never `catch { print(error) }` without context.

## Pattern: StoreKit Review Prompt

With core features stable, we implemented spec 022 — a review prompt that fires after genuine engagement, not on first launch:

```swift
// Review prompt eligibility service.
// Pure logic — no StoreKit dependency. The view layer calls
// requestReview() separately, only when this service says it's time.

@MainActor
@Observable
final class ReviewPromptService {
  private let defaults: UserDefaults

  private var promptCount: Int {
    get { defaults.integer(forKey: "reviewPromptCount") }
    set { defaults.set(newValue, forKey: "reviewPromptCount") }
  }

  private var lastPromptDate: Date? {
    get { defaults.object(forKey: "lastReviewPromptDate") as? Date }
    set { defaults.set(newValue, forKey: "lastReviewPromptDate") }
  }

  private var firstItemDate: Date? {
    get { defaults.object(forKey: "firstItemAddedDate") as? Date }
    set { defaults.set(newValue, forKey: "firstItemAddedDate") }
  }

  var isEligible: Bool {
    // Rule 1: Maximum 2 prompts ever
    guard promptCount < 2 else { return false }

    // Rule 2: At least 30 days since last prompt
    if let last = lastPromptDate {
      let daysSince = Calendar.current.dateComponents(
        [.day], from: last, to: .now
      ).day ?? 0
      guard daysSince >= 30 else { return false }
    }

    // Rule 3: At least 7 days of active use
    guard let firstDate = firstItemDate else { return false }
    let daysSinceFirst = Calendar.current.dateComponents(
      [.day], from: firstDate, to: .now
    ).day ?? 0
    guard daysSinceFirst >= 7 else { return false }

    return true
  }

  func recordPrompt() {
    promptCount += 1
    lastPromptDate = .now
  }

  func recordFirstItem() {
    if firstItemDate == nil {
      firstItemDate = .now
    }
  }
}
```

The service is deliberately decoupled from StoreKit. It answers one question: "is now a good time to ask?" The view calls `requestReview(in:)` separately. This makes the eligibility logic testable without mocking StoreKit.

## Spec Timeline: Days 7–8

| Day | Spec | Action | Why |
|-----|------|--------|-----|
| 7 | 006 | Implement offline resilience | NWPathMonitor queue, background enrichment |
| 7 | 017 | Begin iCloud sync implementation | SwiftData CloudKit, dedup strategy |
| 7 | 010 | Migrate API to Cloudflare Workers proxy | Remove API keys from app binary |
| 7 | — | Add Constitution Principle IX amendment | Constructive errors after debugging sync issues |
| 8 | 022 | **New spec** + implement review prompt | Polish spec, engagement-based triggers |
| 8 | 011 | Disable voice dictation from UI | Latency too high for production UX |
| 8 | 001 | Update spec to match implemented model | Reflect iCloud sync reality |

**New spec:** 022 (Store Review Prompt) — the first "polish" spec. It emerged naturally once core features were stable enough to think about App Store presence.

**Feature freeze:** Day 8 marks the decision to disable voice dictation (spec 011) and the camera scanner (spec 002) from user-facing UI. Both were technically working but not polished enough for the experience we wanted. Voice dictation was later fully removed; the camera feature was reworked on Day 10.

**The API security milestone:** On Day 7, we migrated the external API calls from direct client requests (with the API key embedded in the app binary) to a Cloudflare Workers proxy. The proxy injects the API key server-side, so the app never sees it. This was spec 010's entire purpose, and it took about 20 minutes to implement — the spec had already defined the endpoint format, the error handling, and the fallback behavior.

---

**Total at end of Day 8:**
- 23 feature specs
- 17 specs implemented (2 disabled)
- iCloud sync, offline resilience, review prompts — all working
- API keys removed from app binary
- 357 total commits

Next up: [Days 9–10 — Apple Watch, Spotlight search, and the last mile](/blog/06-watch-spotlight-last-mile.md).

---

*This is Part 5 of a 7-part series. [Read the series overview](/blog/README.md).*
