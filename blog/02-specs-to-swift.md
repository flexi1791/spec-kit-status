# Day 3: From Specs to Swift — SwiftData, Migrations, and Package Architecture

*Part 2 of "10 Days, 400 Commits: Building a Multi-Target iOS 26 App with AI-Driven Spec Development"*

---

The spec said "offline-first with iCloud sync." Three lines of `ModelConfiguration` made that real — but the migration plan is where the spec saved us.

## The Clarification Surge

Day 3 started not with code, but with the most important phase of the entire project: running `/speckit.clarify` on all 12 existing specs. Every single one.

This produced 60+ targeted questions across the specs. Each answer was encoded back into the spec as a clarification amendment. Some examples of what was caught:

- **Spec 001** was missing duplicate detection rules. What happens when the user adds the same item twice? Answer: match on title + category, surface a confirmation dialog.
- **Spec 003** had an ambiguous ownership model. Who owns the category entity — spec 001 (the core data model) or spec 003 (category management)? Answer: spec 003 owns it. Spec 001 references it.
- **Spec 006** overlapped with spec 012. Both described "background data fetching." Answer: spec 012 owns the enrichment pipeline. Spec 006 owns the *queue* — it decides *when* to trigger enrichment based on network state.
- **Spec 009** was missing launch phases entirely. What happens on cold launch? Warm launch? Background wake? Deep link arrival during onboarding? This single clarification expanded spec 009 from a simple tab layout into a full app lifecycle specification.

Twelve specs went in. Twelve *much better* specs came out.

### New Specs from Clarification

Clarification also revealed missing specs. Spec 014 ("Future Technical Considerations") had described widgets, iCloud sync, and Siri integration as "future work." On Day 3, we promoted these to standalone specs:

| New Spec | Promoted From | Why Standalone |
|----------|---------------|----------------|
| 016 | Future spec item F-003 | Widgets need their own data pipeline (App Group shared container) |
| 017 | Future spec item F-001 | iCloud sync touches every model and needs a deduplication strategy |
| 018 | Future spec item F-002 | Siri intents need `@Dependency` injection and entity definitions |

**Total specs: 18.** The architecture was now fully mapped.

## Package Architecture

With specs clarified, we could design the code structure. The constitution (Principle IV — Separation of Models and Views) demanded that business logic live in a dedicated Swift package, independent of UI:

```
src/
  MyApp/                     ← App target (SwiftUI views, navigation)
  MyAppWidget/               ← Widget extension
  MyAppWatch/                ← watchOS companion app
  ShareExtension/            ← Share extension for photo import
  Packages/
    MyKit/                   ← Swift Package (models, services, no UI)
      Sources/
        Models/              ← SwiftData models, schema versions
        Services/            ← Business logic, enrichment, sync
      Tests/
        ModelTests/
        ServiceTests/
```

This separation paid for itself immediately:
- The widget, watch app, and share extension all import `MyKit` without pulling in any UI code
- Tests run with `swift test` — no Xcode build required
- Models and services can be tested independently of the UI

## SwiftData Schema Design

Every spec that touched the data model had a `Data Model Implications` section. Aggregating across all 18 specs gave us the complete schema:

```swift
// The VersionedSchema pattern in Swift 6.2
// Note: nonisolated(unsafe) is required because VersionedSchema
// demands a static var, which Swift 6.2 strict concurrency flags
// as a shared mutable state risk. This is safe because the value
// is set once and never mutated.

enum SchemaV1: VersionedSchema {
  nonisolated(unsafe) static var versionIdentifier: Schema.Version = .init(1, 0, 0)

  static var models: [any PersistentModel.Type] {
    [Item.self, Category.self]
  }

  @Model
  final class Item {
    var title: String
    var dateAdded: Date
    var category: Category?
    var personalNotes: String
    var isCompleted: Bool
    var imageURL: String?

    // Enrichment fields — populated asynchronously after save
    var externalID: String?
    var itemDescription: String?
    var tags: [String]
    var enrichmentStatus: String  // "pending", "enriched", "failed"

    init(title: String, category: Category? = nil) {
      self.title = title
      self.dateAdded = .now
      self.personalNotes = ""
      self.isCompleted = false
      self.tags = []
      self.enrichmentStatus = "pending"
    }
  }

  @Model
  final class Category {
    var name: String
    var isEnabled: Bool
    var iconURL: String?

    init(name: String) {
      self.name = name
      self.isEnabled = false
    }
  }
}
```

### The Migration Plan

Specs predicted we'd need schema migrations. The enrichment pipeline (spec 012) would add fields. iCloud sync (spec 017) would add more. Rather than hoping we'd get the model right the first time, we built the migration infrastructure from day one:

```swift
enum ItemMigrationPlan: SchemaMigrationPlan {
  static var schemas: [any VersionedSchema.Type] {
    [SchemaV1.self]
    // Future versions added here as specs demand them
  }

  static var stages: [MigrationStage] {
    []
    // Lightweight migrations added here
  }
}
```

This empty migration plan might look like over-engineering. It wasn't. When we later needed to add fields for the enrichment pipeline, the infrastructure was already there. We added a `SchemaV2`, wrote one lightweight migration stage, and moved on. Without the spec predicting this need, we'd have been restructuring our model container setup mid-implementation.

## The Shared Model Container

Four targets need to access the same SwiftData store: the app, the widget, the watch payload builder, and the share extension. This is the `SharedModelContainer` pattern:

```swift
// Multi-target SwiftData container with CloudKit fallback
// Uses App Group for cross-target access and CloudKit for iCloud sync.
// Falls back gracefully if CloudKit is unavailable (e.g., simulator,
// no iCloud account, or entitlement issues).

import SwiftData
import os

struct SharedContainer {
  private static let logger = Logger(
    subsystem: "com.example.app",
    category: "ModelContainer"
  )

  static func create() throws -> ModelContainer {
    let schema = Schema(versionedSchema: SchemaV1.self)

    // Attempt 1: App Group + CloudKit (production path)
    do {
      let config = ModelConfiguration(
        schema: schema,
        groupContainer: .identifier("group.com.example.shared"),
        cloudKitDatabase: .private("iCloud.com.example.app")
      )
      return try ModelContainer(
        for: schema,
        migrationPlan: ItemMigrationPlan.self,
        configurations: [config]
      )
    } catch {
      logger.warning("CloudKit container failed: \(error). Falling back to local.")
    }

    // Attempt 2: App Group only (no iCloud account or simulator)
    let fallback = ModelConfiguration(
      schema: schema,
      groupContainer: .identifier("group.com.example.shared")
    )
    return try ModelContainer(
      for: schema,
      migrationPlan: ItemMigrationPlan.self,
      configurations: [fallback]
    )
  }
}
```

The try-catch fallback was born from a clarification question on spec 017: *"What happens when the user has no iCloud account?"* The spec said: degrade to local storage. The code does exactly that.

## Swift Testing, Not XCTest

The constitution was explicit: **Swift Testing only. No XCTest.** This was a deliberate choice for several reasons:

1. **Swift Testing uses `@Test` and `#expect`** — more expressive than `XCTAssertEqual`
2. **Parameterized tests** with `@Test(arguments:)` eliminate boilerplate
3. **Tags and traits** replace XCTest's class-based organization
4. **`.serialized` trait** controls execution order without subclassing

Here's the testing pattern we established for SwiftData models:

```swift
import Testing
import SwiftData
@testable import MyKit

@Suite(.serialized)
@MainActor
struct ItemModelTests {
  let container: ModelContainer

  init() throws {
    // In-memory container for test isolation
    let config = ModelConfiguration(isStoredInMemoryOnly: true)
    container = try ModelContainer(
      for: SchemaV1.Item.self, SchemaV1.Category.self,
      configurations: config
    )
  }

  @Test func itemDefaultsToCorrectState() throws {
    let context = container.mainContext
    let item = SchemaV1.Item(title: "Test Title")
    context.insert(item)
    try context.save()

    let fetched = try context.fetch(FetchDescriptor<SchemaV1.Item>())
    #expect(fetched.count == 1)
    #expect(fetched[0].title == "Test Title")
    #expect(fetched[0].enrichmentStatus == "pending")
    #expect(fetched[0].isCompleted == false)
  }

  @Test(arguments: ["", "   ", "\n"])
  func emptyTitlesArePreserved(title: String) throws {
    // Validation happens at the UI layer, not the model layer.
    // The model stores whatever it's given.
    let item = SchemaV1.Item(title: title)
    #expect(item.title == title)
  }
}
```

One hard lesson: **multiple `@MainActor` test suites creating separate `ModelContainer` instances across different files causes signal 4 crashes** in `swift test`. The fix was consolidating SwiftData tests into fewer files, using the `.serialized` trait, and running `swift test --no-parallel`. This is a Swift Testing + SwiftData rough edge that isn't well documented yet.

## Spec Timeline: Day 3

| Time | Action | Why |
|------|--------|-----|
| Morning | `/speckit.clarify` on all 12 specs | Fix scope gaps before implementation |
| Mid-morning | Create specs 013–015 | Manual input, future considerations, monetization |
| Mid-day | Promote future items to specs 016–018 | Widgets, iCloud, and Siri need standalone specs |
| Afternoon | Generate implementation plans for specs 001, 003, 009, 013 | High-dependency specs planned first |
| Evening | Requirements quality checklists | Final validation before implementation |

**Commits: 60. Lines of Swift: still 0.** (Well, almost zero — the package structure and model stubs were in place.)

## The Decision to Wait

Three days in, a reasonable person might ask: *"Why haven't you written any real code yet?"*

The answer became obvious on Day 4, when we implemented 9 specs in a single day — 81 commits of production code, guided by plans that already knew which files to create, which services to inject, and which edge cases to handle.

The specs didn't slow us down. They were the reason Day 4 was even possible.

---

**Total at end of Day 3:**
- 18 feature specs (12 clarified, 6 new)
- 1 constitution (v1.5.0)
- Package structure established
- SwiftData schema with migration infrastructure
- Swift Testing patterns validated
- 154 total commits

Next up: [Day 4 — 81 commits and the implementation explosion](/blog/03-implementation-explosion.md).

---

*This is Part 2 of a 7-part series. [Read the series overview](/blog/README.md).*
