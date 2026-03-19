# Days 5–6: Vision OCR, Siri App Intents, and Deep Linking

*Part 4 of "10 Days, 400 Commits: Building a Multi-Target iOS 26 App with AI-Driven Spec Development"*

---

Siri, the camera, and a share sheet walk into an app. Making them all resolve to the same data pipeline is the real engineering challenge.

## The Intelligence Layer

Days 5 and 6 were about input diversity. The app already had manual text input (spec 013). Now we added three more ways to get data in:

1. **Vision OCR** — Point your camera at a screen, extract text automatically
2. **Siri App Intents** — "Hey Siri, add an entry to my collection"
3. **Share extension** — Share a photo from another app, OCR extracts the text

And one critical way to get data *out*:

4. **Universal links** — Share a deep link that opens directly to content in the app

All four of these funnel into the same enrichment pipeline from Day 4. That convergence was specified in the plans — and it made implementation clean.

## Pattern: Vision OCR Pipeline

iOS 18 introduced the new `RecognizeTextRequest` API in the Vision framework. It replaces the older `VNRecognizeTextRequest` with a simpler, more Swift-native interface:

```swift
import Vision

// Stateless OCR service using iOS 18+ Vision API.
// Returns recognized text blocks from a CGImage.

struct OCRService: Sendable {
  func recognizeText(in image: CGImage) async throws -> [String] {
    var request = RecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true

    let observations = try await request.perform(on: image)

    return observations
      .compactMap { $0.topCandidates(1).first?.string }
      .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
  }
}
```

The new API is `async` natively — no completion handlers, no request queuing. And the service is a `Sendable` struct with no mutable state, so it's safe to call from any concurrency context.

We paired this with a detection service that analyzes the OCR results to identify known keywords:

```swift
// Identifies a known category from OCR text by matching against
// a dictionary of keywords and aliases.

struct DetectionService: Sendable {
  private let knownCategories: [String: [String]]  // name → [keywords]

  func detect(from textBlocks: [String]) -> String? {
    let combined = textBlocks
      .joined(separator: " ")
      .lowercased()

    for (name, keywords) in knownCategories {
      for keyword in keywords {
        if combined.contains(keyword.lowercased()) {
          return name
        }
      }
    }
    return nil
  }
}
```

**What the spec caught:** Spec 020 (OCR detection) was originally embedded in spec 002 (photo input). During clarification, we extracted it into its own spec because the detection logic is reusable — the share extension, the camera, and even future clipboard-paste features all need it. This extraction was a clarification win.

## Pattern: Siri App Intents with SwiftData

App Intents in iOS 26 can access SwiftData via `@Dependency` injection. This is the cleanest way to let Siri read and write your data model:

```swift
import AppIntents
import SwiftData

struct AddItemIntent: AppIntent {
  static var title: LocalizedStringResource = "Add Item"
  static var description = IntentDescription("Add a new item to your collection.")

  @Parameter(title: "Title")
  var title: String

  @Parameter(title: "Category")
  var category: CategoryEntity?

  static var parameterSummary: some ParameterSummary {
    Summary("Add \(\.$title) to \(\.$category)")
  }

  // SwiftData container injected by the system
  @Dependency
  private var modelContainer: ModelContainer

  @MainActor
  func perform() async throws -> some IntentResult & ProvidesDialog {
    let context = modelContainer.mainContext

    // Check for duplicates using the same logic as the UI
    let existing = try context.fetch(
      FetchDescriptor<SchemaV1.Item>(
        predicate: #Predicate { $0.title == title }
      )
    )

    if let duplicate = existing.first {
      return .result(dialog: "'\(title)' is already in your collection.")
    }

    // Create and save
    let item = SchemaV1.Item(title: title)
    if let categoryName = category?.name {
      item.category = try resolveCategory(named: categoryName, in: context)
    }
    context.insert(item)
    try context.save()

    return .result(dialog: "Added '\(title)' to your collection.")
  }

  private func resolveCategory(
    named name: String,
    in context: ModelContext
  ) throws -> SchemaV1.Category? {
    let descriptor = FetchDescriptor<SchemaV1.Category>(
      predicate: #Predicate { $0.name == name }
    )
    return try context.fetch(descriptor).first
  }
}
```

Key details:
- **`@Dependency private var modelContainer`** — The system injects the same container your app uses. Register it in your `App` struct with `.modelContainer(for:)` and it's automatically available to intents.
- **`@MainActor func perform()`** — SwiftData's `mainContext` is main-actor-isolated. The intent must run on the main actor to access it.
- **Duplicate detection** — The intent uses the same logic as the UI layer. This was specified in the plan: "reuse `findDuplicate()` from the resolution pipeline."

### The Sandbox Problem

One gotcha with App Intents: **Siri runs your intent in a limited sandbox**. If your enrichment pipeline calls an external API, that API call may not have the same entitlements as your main app. We solved this by creating a `NoOpLookupService` for the intent context — the item gets saved with `enrichmentStatus: "pending"`, and the main app's coordinator picks it up for enrichment the next time it launches.

```swift
// No-op lookup for contexts without full network access.
// Items are saved as "pending" and enriched later by the main app.
struct NoOpLookupService: LookupServiceProtocol {
  func lookup(title: String) async throws -> LookupResult {
    throw LookupError.unavailable(reason: "Enrichment deferred to main app")
  }
}
```

## Deep Linking Architecture

This was the most cross-cutting feature of the project. Universal links touch the web server, the app delegate, the navigation state, the share extension, and even the onboarding flow.

### Step 1: Apple App Site Association

The web server hosts a `/.well-known/apple-app-site-association` file:

```json
{
  "applinks": {
    "details": [{
      "appIDs": ["TEAMID.com.example.app"],
      "components": [{
        "/": "/item/*"
      }]
    }]
  }
}
```

### Step 2: URL Construction

Share payloads encode data as query parameters, not path components. This keeps the URL parseable even when titles contain special characters:

```swift
// Constructs a shareable URL with all metadata as query parameters.
// Handles both HTTPS universal links and custom URL schemes.

struct ShareURL: Sendable {
  let title: String
  let categoryName: String?
  let senderName: String?
  let externalID: String?

  func buildURL(baseURL: URL) -> URL {
    var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
    var queryItems: [URLQueryItem] = [
      URLQueryItem(name: "title", value: title)
    ]
    if let categoryName {
      queryItems.append(URLQueryItem(name: "category", value: categoryName))
    }
    if let senderName {
      queryItems.append(URLQueryItem(name: "from", value: senderName))
    }
    if let externalID {
      queryItems.append(URLQueryItem(name: "id", value: externalID))
    }
    components.queryItems = queryItems
    return components.url!
  }

  init?(from url: URL) {
    guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
          let title = components.queryItems?.first(where: { $0.name == "title" })?.value
    else { return nil }

    self.title = title
    self.categoryName = components.queryItems?.first(where: { $0.name == "category" })?.value
    self.senderName = components.queryItems?.first(where: { $0.name == "from" })?.value
    self.externalID = components.queryItems?.first(where: { $0.name == "id" })?.value
  }
}
```

### Step 3: Multi-Strategy Deep Link Routing

The app must handle three types of incoming URLs, all in the `.onOpenURL` modifier:

```swift
@main
struct MyApp: App {
  @State private var pendingItemID: String?
  @AppStorage("hasCompletedOnboarding") private var hasCompletedOnboarding = false

  var body: some Scene {
    WindowGroup {
      ContentView(pendingItemID: $pendingItemID)
        .onOpenURL { url in
          handleDeepLink(url)
        }
        .onContinueUserActivity(
          CSSearchableItemActionType
        ) { activity in
          // Spotlight tap → extract item identifier
          if let id = activity.userInfo?[CSSearchableItemActivityIdentifier] as? String {
            pendingItemID = id
          }
        }
    }
  }

  private func handleDeepLink(_ url: URL) {
    // Strategy 1: Universal link (https://example.com/item/?title=...)
    if let sharePayload = ShareURL(from: url) {
      // Resolve or create item from share data
      resolveSharedItem(sharePayload)
      return
    }

    // Strategy 2: Share extension handoff (myapp://import-photo)
    if url.scheme == "myapp", url.host == "import-photo" {
      handlePhotoImport()
      return
    }

    // Strategy 3: Custom scheme deep link (myapp://item/ABC123)
    if url.scheme == "myapp", url.host == "item" {
      pendingItemID = url.lastPathComponent
    }
  }
}
```

### Step 4: The Cold Launch Problem

Universal links arrive *before* the SwiftUI view hierarchy is fully loaded. If the user taps a shared link and the app isn't running, `onOpenURL` fires before your views are ready to navigate.

The fix: store the pending navigation target in `@State` and let the view consume it when it's ready:

```swift
struct ContentView: View {
  @Binding var pendingItemID: String?

  var body: some View {
    TabView {
      ItemListView(pendingItemID: $pendingItemID)
      // ...
    }
    .onChange(of: pendingItemID) { _, newValue in
      // Navigate when the view is ready, not when the URL arrives
      if let id = newValue {
        navigateToItem(id: id)
        pendingItemID = nil
      }
    }
  }
}
```

**What the spec caught:** Spec 009's clarification asked "What happens when a universal link arrives during onboarding?" This led to the guard: if `!hasCompletedOnboarding`, store the deep link and defer navigation until onboarding completes. Without that question, the first shared link a new user tapped would silently fail.

### Step 5: Web Landing Page

What if the recipient doesn't have the app installed? The universal link falls through to the web. We deployed a simple HTML page at the same URL path that shows the shared content and an App Store install button:

```html
<!-- /item/index.html — fallback for users without the app -->
<script>
  const params = new URLSearchParams(window.location.search);
  document.getElementById('title').textContent = params.get('title') || 'Shared Item';
  document.getElementById('from').textContent = params.get('from')
    ? `Shared by ${params.get('from')}` : '';
</script>
```

This is hosted on Cloudflare Pages alongside the API proxy — zero additional infrastructure.

## What Didn't Work: Voice Dictation

We should talk about spec 011.

The plan was ambitious: tap and hold a microphone button, speak a title, and have on-device ML parse it into structured data. We used Apple's `FoundationModels` framework (`LanguageModelSession` with `@Generable` types) for the NLP, and `AVAudioEngine` for the audio capture.

It worked. Technically. The speech-to-text was accurate. The NLP parsing was solid. The pipeline resolved spoken input into the same enrichment flow as everything else.

But the *experience* was terrible.

**The problem was latency.** `FoundationModels` needs a few seconds to initialize its language model session. `AVAudioEngine` needs time to configure the audio session and request microphone permission. Combined, there was a 3–4 second delay between the user tapping the mic button and the system being ready to listen.

During that delay, the user is holding the button and speaking — but the system isn't listening yet. Or the user is waiting, unsure if anything is happening. Or the system captures only the tail end of what was said.

No amount of UI polish — loading indicators, haptic feedback, "listening..." labels — could fix the fundamental issue: **the latency was in the wrong place**. A camera opens instantly. Text input is instant. Voice input with a multi-second preamble feels broken.

We removed the feature entirely on Day 8. Not disabled, not hidden behind a flag — removed. The spec, the plan, the code: all deleted.

**The lesson:** On-device ML has real latency costs that specs can't predict. You can spec the ideal UX, but you can't spec away framework startup time. Some things you only discover by building them.

## Spec Timeline: Days 5–6

| Day | Spec | Action | Why |
|-----|------|--------|-----|
| 5 | 011 | Implement voice dictation | Mic + FoundationModels NLP (later removed) |
| 5 | 020 | **New spec** + implement OCR detection | Extracted from spec 002 as reusable service |
| 5 | 003 | Expand implementation | 20 predefined categories, icon grid |
| 6 | 005 | Implement filter, search & share | Tag chips, multi-select, rich share |
| 6 | 018 | Implement Siri App Intents | Headless add/query via Siri |
| 6 | 021 | **New spec** + implement universal links | Deep link architecture, web landing page |

Two new specs emerged organically:
- **Spec 020** (OCR detection) was extracted from spec 002 because the detection logic was useful in multiple contexts
- **Spec 021** (universal links) was created when the share feature (spec 005) needed a URL format definition

**Total specs: 23. Total commits: 317.**

---

Next up: [Days 7–8 — iCloud sync, deduplication, and the hard work of making things reliable offline](/blog/05-icloud-sync-offline.md).

---

*This is Part 4 of a 7-part series. [Read the series overview](/blog/README.md).*
