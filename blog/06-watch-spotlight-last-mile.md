# Days 9–10: Apple Watch, Spotlight, and the Last Mile

*Part 6 of "10 Days, 400 Commits: Building a Multi-Target iOS 26 App with AI-Driven Spec Development"*

---

WatchConnectivity has a race condition that will silently drop your first message. Here's the buffering pattern that fixes it.

## The Ecosystem Expansion

Days 9 and 10 were about breadth. The iPhone app was feature-complete. Now we needed to push it out to three more surfaces:

1. **Apple Watch companion** — Read-only view of recent items, synced from iPhone
2. **Spotlight search** — Index items in CoreSpotlight for system-wide search
3. **Photo share extension** — Accept images from other apps, OCR the text, create items

Three new specs (023, 024, 025) were created and implemented in two days. This was the "one more thing" phase — and it revealed that cross-platform complexity is where spec-driven development earns its keep.

## The Watch Misconception: App Groups Are Single-Device Only

Our first instinct for iPhone-to-Watch data sync was to use the App Group shared container — the same pattern that works for the widget:

```swift
// This works for iPhone ↔ Widget (same device, different processes)
let config = ModelConfiguration(
  groupContainer: .identifier("group.com.example.shared")
)
```

**This does not work for iPhone ↔ Apple Watch.**

App Groups share data between processes on the *same physical device*. The widget and the app both run on the iPhone — they can share a SQLite file through the group container. The Apple Watch is a separate device. It has its own file system.

This seems obvious in hindsight, but it's a common misconception, especially if you've been building widget support and the pattern is fresh in your mind. The spec process caught it during clarification:

> **Q: How does data flow from iPhone to Apple Watch? The shared container in spec 016 (widgets) uses App Groups, but Watch is a separate device.**
>
> A: WatchConnectivity. The iPhone serializes items into a JSON payload and pushes it to the watch via `WCSession`. The watch stores the payload in local UserDefaults and renders from there.

This single clarification saved us from building the wrong architecture entirely.

## Pattern: Reliable WatchConnectivity with Message Buffering

`WCSession` has a timing problem. Your app might try to send data to the watch before the session has finished activating. If you call `sendMessage` or `updateApplicationContext` before `activationState == .activated`, the call silently fails.

The fix is a buffering pattern that queues messages until the session is ready:

```swift
import WatchConnectivity

// Manages WatchConnectivity from the iPhone side.
// Buffers outgoing data until the session is activated,
// then flushes with a dual-delivery strategy.

final class PhoneSessionManager: NSObject, WCSessionDelegate, @unchecked Sendable {
  static let shared = PhoneSessionManager()

  private let session = WCSession.default
  private let queue = DispatchQueue(label: "PhoneSessionManager")

  // Buffer for data that arrives before session activation
  private var pendingPayload: [[String: Any]]?

  override init() {
    super.init()
    session.delegate = self
    session.activate()
  }

  // MARK: - Public API

  func pushItems(_ items: [[String: Any]]) {
    queue.async { [self] in
      guard session.activationState == .activated else {
        // Session isn't ready — buffer the data
        #if DEBUG
        print("[PhoneSession] Buffering \(items.count) items (session not activated)")
        #endif
        pendingPayload = items
        return
      }
      send(items)
    }
  }

  // MARK: - Delivery

  private func send(_ items: [[String: Any]]) {
    let payload: [String: Any] = [
      "items": items,
      "timestamp": Date().timeIntervalSince1970
    ]

    // Strategy 1: Application context (persisted, delivered on next wake)
    // This is the reliable path — data survives app termination.
    do {
      try session.updateApplicationContext(payload)
      #if DEBUG
      print("[PhoneSession] Updated application context with \(items.count) items")
      #endif
    } catch {
      #if DEBUG
      print("[PhoneSession] Application context failed: \(error)")
      #endif
    }

    // Strategy 2: Send message (immediate, but only if watch app is reachable)
    // This provides real-time updates when the watch app is in the foreground.
    if session.isReachable {
      session.sendMessage(payload, replyHandler: nil) { error in
        #if DEBUG
        print("[PhoneSession] Send message failed: \(error)")
        #endif
      }
    }
  }

  // MARK: - WCSessionDelegate

  func session(
    _ session: WCSession,
    activationDidCompleteWith activationState: WCSessionActivationState,
    error: Error?
  ) {
    queue.async { [self] in
      if let pending = pendingPayload {
        #if DEBUG
        print("[PhoneSession] Flushing \(pending.count) buffered items after activation")
        #endif
        send(pending)
        pendingPayload = nil
      }
    }
  }

  func sessionDidBecomeInactive(_ session: WCSession) {}
  func sessionDidDeactivate(_ session: WCSession) {
    session.activate()  // Re-activate for next transfer
  }
}
```

### The Dual-Delivery Strategy

Two delivery mechanisms, each solving a different problem:

| Mechanism | When it works | Persistence | Latency |
|-----------|---------------|-------------|---------|
| `updateApplicationContext` | Always (after activation) | Survives termination | Next wake |
| `sendMessage` | Only when watch app is reachable | None | Immediate |

Using both ensures that:
- Data is **always delivered** (via application context, even if the watch app isn't running)
- Data is **immediately visible** when the watch app is open (via send message)
- The watch app receives data **on first launch** (the last application context is delivered in `session(_:didReceiveApplicationContext:)`)

### Watch-Side Receiver

The watch mirrors this with a session manager that reads from both channels:

```swift
import WatchConnectivity
import SwiftUI

// Watch-side session manager.
// Receives data from both sendMessage and applicationContext,
// persists to UserDefaults for offline access.

@MainActor
final class WatchSessionManager: NSObject, ObservableObject, WCSessionDelegate,
  @unchecked Sendable
{
  @Published var items: [WatchItem] = []

  private let session = WCSession.default
  private let storageKey = "cached_items"

  override init() {
    super.init()
    session.delegate = self
    session.activate()

    // Load cached data from last session
    loadFromCache()
  }

  // MARK: - WCSessionDelegate

  nonisolated func session(
    _ session: WCSession,
    activationDidCompleteWith state: WCSessionActivationState,
    error: Error?
  ) {
    // Check if there's a pending application context from the phone
    if !session.receivedApplicationContext.isEmpty {
      Task { @MainActor in
        self.processPayload(session.receivedApplicationContext)
      }
    }
  }

  nonisolated func session(
    _ session: WCSession,
    didReceiveApplicationContext context: [String: Any]
  ) {
    Task { @MainActor in
      self.processPayload(context)
    }
  }

  nonisolated func session(
    _ session: WCSession,
    didReceiveMessage message: [String: Any]
  ) {
    Task { @MainActor in
      self.processPayload(message)
    }
  }

  // MARK: - Processing

  private func processPayload(_ payload: [String: Any]) {
    guard let rawItems = payload["items"] as? [[String: Any]] else { return }
    items = rawItems.compactMap { WatchItem(from: $0) }
    saveToCache()
  }

  private func loadFromCache() {
    guard let data = UserDefaults.standard.data(forKey: storageKey),
          let cached = try? JSONDecoder().decode([WatchItem].self, from: data)
    else { return }
    items = cached
  }

  private func saveToCache() {
    if let data = try? JSONEncoder().encode(items) {
      UserDefaults.standard.set(data, forKey: storageKey)
    }
  }
}
```

The watch-side pattern:
- **Three receive paths** — activation (for cached context), `didReceiveApplicationContext` (background delivery), `didReceiveMessage` (foreground delivery)
- **UserDefaults cache** — The watch app can launch without the phone nearby and still show the last-synced data
- **`nonisolated` delegates, `@MainActor` processing** — WCSession calls delegates on a background thread. We marshal to the main actor for UI updates.

## Pattern: CoreSpotlight Indexing

Spec 024 (Spotlight Search) was one of the cleanest implementations — partly because CoreSpotlight's API maps directly to our data model:

```swift
import CoreSpotlight

// Indexes items in Spotlight for system-wide search.
// Uses a domain identifier for bulk cleanup when items are deleted.
// Stateless struct — safe to create and discard freely.

struct SpotlightIndexService: Sendable {
  private static let domainID = "com.example.app.items"

  func index(_ item: SchemaV1.Item, thumbnailURL: URL? = nil) {
    let attributes = CSSearchableItemAttributeSet(contentType: .content)
    attributes.title = item.title
    attributes.contentDescription = item.personalNotes.isEmpty
      ? item.itemDescription
      : item.personalNotes
    attributes.keywords = item.tags

    if let url = thumbnailURL {
      attributes.thumbnailURL = url
    }

    let searchItem = CSSearchableItem(
      uniqueIdentifier: item.persistentModelID.storeIdentifier,
      domainIdentifier: Self.domainID,
      attributeSet: attributes
    )

    CSSearchableIndex.default().indexSearchableItems([searchItem])
  }

  func remove(identifier: String) {
    CSSearchableIndex.default().deleteSearchableItems(
      withIdentifiers: [identifier]
    )
  }

  @MainActor
  func reindexAll(items: [SchemaV1.Item]) async {
    // Clear everything in our domain, then re-index
    CSSearchableIndex.default().deleteSearchableItems(
      withDomainIdentifiers: [Self.domainID]
    ) { error in
      #if DEBUG
      if let error { print("[Spotlight] Domain cleanup failed: \(error)") }
      #endif
    }

    for item in items {
      index(item)
    }
  }
}
```

The domain identifier pattern is underused. By assigning all items the same domain, `reindexAll` can clear the entire domain in one call instead of tracking individual identifiers. This is especially useful after iCloud sync — when deduplication changes item identifiers, a full reindex is simpler than trying to update individual records.

### Spotlight → Deep Link

When a user taps a Spotlight result, the app receives a `CSSearchableItemActionType` user activity:

```swift
.onContinueUserActivity(CSSearchableItemActionType) { activity in
  if let identifier = activity.userInfo?[CSSearchableItemActivityIdentifier] as? String {
    pendingItemID = identifier
  }
}
```

This feeds into the same deep link routing from Day 6. The identifier is the SwiftData persistent model ID, so navigation resolves directly to the item.

## Pattern: Share Extension → Host App

The share extension (spec 025) accepts photos from other apps, but it can't run the full enrichment pipeline (it's a limited process). Instead, it saves the image and deep links back to the host app:

```swift
// Share extension principal class.
// Saves the shared image to the App Group container,
// then opens the main app via a custom URL scheme.

import UIKit
import UniformTypeIdentifiers

class ShareViewController: UIViewController {
  override func viewDidAppear(_ animated: Bool) {
    super.viewDidAppear(animated)
    processSharedItems()
  }

  private func processSharedItems() {
    guard let items = extensionContext?.inputItems as? [NSExtensionItem] else {
      close()
      return
    }

    for item in items {
      for provider in item.attachments ?? [] {
        if provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
          provider.loadItem(forTypeIdentifier: UTType.image.identifier) { [weak self] data, _ in
            if let url = data as? URL, let imageData = try? Data(contentsOf: url) {
              self?.saveAndHandoff(imageData)
            }
          }
          return
        }
      }
    }
    close()
  }

  private func saveAndHandoff(_ imageData: Data) {
    // Write to shared container (App Group)
    let container = FileManager.default.containerURL(
      forSecurityApplicationGroupIdentifier: "group.com.example.shared"
    )
    let imageURL = container?.appendingPathComponent("shared-import.jpg")

    if let imageURL {
      try? imageData.write(to: imageURL)
    }

    // Open main app to process the image
    let handoffURL = URL(string: "myapp://import-photo")!
    DispatchQueue.main.async {
      self.extensionContext?.open(handoffURL) { _ in
        self.close()
      }
    }
  }

  private func close() {
    extensionContext?.completeRequest(returningItems: nil)
  }
}
```

The host app's deep link handler (from Day 6) picks up the `myapp://import-photo` URL, reads the image from the shared container, runs OCR, and creates the item — all within the full app context with access to the enrichment pipeline.

## Conditional Compilation for Multi-Platform

`MyKit` is shared between iOS and watchOS. Some APIs are iOS-only:

```swift
// CoreSpotlight is not available on watchOS.
// Guard the import and all usage with #if canImport.

#if canImport(CoreSpotlight)
import CoreSpotlight
#endif

struct SpotlightIndexService: Sendable {
  func index(_ item: SchemaV1.Item) {
    #if canImport(CoreSpotlight)
    // ... indexing code ...
    #endif
  }
}
```

Similarly, UIKit-dependent code (like `CGImage` conversion for OCR) uses `#if os(iOS)`:

```swift
#if os(iOS)
import UIKit

extension CGImage {
  static func from(data: Data) -> CGImage? {
    UIImage(data: data)?.cgImage
  }
}
#endif
```

These guards are invisible at the call site — the compiler strips the code for unsupported platforms. The spec identified which services needed guards during the planning phase, so we didn't discover platform incompatibilities at build time.

## Spec Timeline: Days 9–10

| Day | Spec | Action | Why |
|-----|------|--------|-----|
| 9 | 017 | Complete iCloud sync implementation | Dedup, reactive triggers, data repair |
| 9 | 023 | **New spec**: Apple Watch companion | Read-only view of recent items |
| 10 | 024 | **New spec** + implement Spotlight search | CoreSpotlight indexing, deep linking |
| 10 | 025 | **New spec** + implement share extension | Photo import via OCR |
| 10 | 023 | Implement Watch companion | watchOS app, WatchConnectivity, UI |
| 10 | 002 | Rework camera feature | Replace custom scanner with Apple Live Text |

Three new specs in two days — all ecosystem extensions. The camera feature (spec 002) was reworked: we replaced our custom camera capture view with Apple's Live Text integration, which was simpler, more familiar to users, and required less code.

**The UI oscillation:** On Day 10, the camera UI changed direction three times — custom scanner → Apple Live Text → VisionKit document scanner → back to Live Text. This is the "last mile" reality: cross-platform features interact in unexpected ways, and the right answer sometimes takes a few iterations to find.

## The Race Condition Fix

Day 10 ended with a critical bug: the first WatchConnectivity push after app launch was silently dropped. The sequence:

1. App launches, creates `PhoneSessionManager`
2. User adds an item, triggers `pushItems()`
3. `WCSession.activationState` is still `.notActivated`
4. The push goes into the buffer
5. `activationDidCompleteWith` fires... but the buffer was already flushed (incorrectly)

The fix was the buffering pattern shown above — check activation state *synchronously* on a private queue, buffer if not ready, flush exactly once when activation completes. The dual-delivery strategy (`updateApplicationContext` + `sendMessage`) was added as belt-and-suspenders insurance.

---

**Total at end of Day 10:**
- 25 feature specs
- 20 specs implemented
- iPhone app, Apple Watch companion, widget, share extension — all working
- iCloud sync with deduplication
- Spotlight search indexing
- WatchConnectivity with reliable delivery
- 410 total commits

Next up: [The retrospective — what worked, what didn't, and what to steal](/blog/07-retrospective.md).

---

*This is Part 6 of a 7-part series. [Read the series overview](/blog/README.md).*
