# Retrospective: What Worked, What Didn't, What to Steal

*Part 7 of "10 Days, 400 Commits: Building a Multi-Target iOS 26 App with AI-Driven Spec Development"*

---

We built a 4-target iOS 26 app in 10 days. The secret was not writing code faster — it was spending 3 days not writing code at all.

## By the Numbers

| Metric | Value |
|--------|-------|
| Calendar days | 10 (Mar 9–19) |
| Total commits | 416 |
| Feature specs created | 25 |
| Specs implemented | 20 |
| Lines of Swift | ~15,000 |
| Targets | 4 (iOS app, watchOS app, widget, share extension) |
| Swift Package (shared) | ~8,200 LOC (models + services) |
| App target | ~6,000 LOC (views + navigation) |
| Test files | 23 (Swift Testing, not XCTest) |
| Constitution revisions | 16 (v1.0.0 → v1.16.0) |
| Features removed | 1 (voice dictation) |

### Commits Per Day

```
Mar  9  ████████████████████████████                          56
Mar 10  █████████████████████                                 42
Mar 11  ██████████████████████████████                        60
Mar 12  ████████████████████████████████████████████████████  81  ← PEAK
Mar 13  ██████████████████████████████                        60
Mar 14  ███████████                                           22
Mar 15  █████████████                                         27
Mar 16  ██████                                                13
Mar 17  ████                                                   9
Mar 18  ████████████████████                                  40
Mar 19  ███                                                    6
```

The shape tells the story: **spec work** (Days 1–3), **implementation explosion** (Days 4–5), **hardening** (Days 6–8), **ecosystem expansion** (Days 9–10).

### Spec Growth Over Time

```
Day  1: ███                                   3 specs
Day  2: ████████████                         12 specs
Day  3: ██████████████████                   18 specs
Day  4: █████████████████████                21 specs
Day  5: ███████████████████████              23 specs
Day  8: ███████████████████████              23 specs (+ 1 removed)
Day 10: █████████████████████████            25 specs
```

Specs weren't all created upfront. They grew organically:
- **Days 1–3:** Foundation (12 specs) + promoted future items (6 specs)
- **Days 4–5:** Implementation insights spawned new specs (3 specs from seeing what was missing)
- **Day 8:** Polish spec (1 review prompt spec) + feature removal
- **Day 10:** Ecosystem expansion (3 specs for Watch, Spotlight, Share Extension)

This organic growth is healthy. Specs that emerge from implementation are *grounded* — they solve real problems the developer just encountered, not hypothetical ones.

## What Worked

### 1. The Constitution Settled Debates Before They Started

Every architectural disagreement was pre-resolved:
- "UIKit or SwiftUI?" → Principle I: SwiftUI-first, UIKit only when necessary
- "How much error handling?" → Principle IX: Constructive errors, never silent
- "Should we abstract this?" → Principle VII: Lean code, no unnecessary abstractions
- "Can we store this in the cloud?" → Principle II: On-device by default
- "XCTest or Swift Testing?" → Principle VIII: Swift Testing, always

The constitution was amended 16 times, but the core principles never changed. Amendments *added* clarity (like Principle IX on constructive errors, added on Day 7 after debugging opaque CloudKit failures). They never contradicted earlier decisions.

**Steal this:** Write 5–10 project principles before you write code. Be specific enough that they resolve real debates. Amend as needed, but don't contradict.

### 2. Clarification Caught 90% of Edge Cases

The `/speckit.clarify` phase asked questions we wouldn't have thought of:
- *"What happens when a universal link arrives during onboarding?"* — Led to the pending deep link pattern
- *"How does data flow from iPhone to Apple Watch?"* — Prevented building on the wrong architecture (App Groups vs. WatchConnectivity)
- *"Can the user edit the title after enrichment?"* — Prevented orphaned metadata
- *"What's the deduplication strategy when the same item syncs from two devices?"* — Led to the richness-scored merge algorithm

Each of these would have been a multi-hour debugging session or a late redesign. Instead, they were caught as Markdown amendments before any code existed.

**Steal this:** Before implementing any spec, have someone (or an AI) ask 5 adversarial questions about the edge cases. Encode the answers into the spec.

### 3. Day 4's Explosion Was Only Possible Because Days 1–3 Were "Slow"

81 commits in one day. 9 specs implemented. This wasn't heroic coding — it was *mechanical translation*. Every task said which file to create, which protocol to conform to, which edge cases to handle. The AI wasn't making decisions; it was executing them.

If we'd started coding on Day 1, we would have:
- Redesigned the data model at least twice
- Discovered spec 003 and spec 001 had conflicting ownership of the category entity
- Built the enrichment pipeline before the data model was stable
- Missed the widget's need for a shared container
- Built WatchConnectivity before realizing it needed a buffering pattern

The "slow" days made the "fast" days possible.

**Steal this:** Resist the urge to code immediately. Spend 20–30% of your project timeline on specification and clarification. The implementation phase will compress dramatically.

### 4. The Spec-as-Living-Document Pattern

Specs weren't write-once artifacts. They were updated throughout:
- **Pre-implementation:** Clarification amendments
- **During implementation:** Edge cases discovered, added as new FRs
- **Post-implementation:** Reality checks, model ownership transfers
- **After feature removal:** Spec marked as removed with rationale

This living-document approach meant the specs stayed accurate. At any point, you could read a spec and know the current state of the feature — not just the original vision.

## What Didn't Work

### 1. Voice Dictation (The Latency Problem)

Full story in [Post 4](/blog/04-vision-siri-deep-links.md). Short version: `FoundationModels` session initialization + `AVAudioEngine` audio session setup created a 3–4 second delay before the microphone was live. No amount of UI polish fixed the fundamental UX issue. Feature was removed entirely.

**Lesson:** On-device ML has real startup costs that specs can't predict. Prototype latency-sensitive features early, before building the full pipeline around them.

### 2. App Groups ≠ Watch Data Sync

We initially assumed the widget pattern (App Group shared container) would work for the Apple Watch. It doesn't — App Groups share data between processes on the same device. The Watch is a separate device.

This was caught during clarification (see Post 6), but if we hadn't asked the question, we would have built the wrong architecture and discovered the problem after deployment.

**Lesson:** Patterns that work for one target don't automatically transfer to others. Cross-platform data flow needs explicit specification.

### 3. UI Oscillation on Cross-Platform Features

The camera UI changed direction three times on Day 10: custom scanner → Apple Live Text → VisionKit document scanner → back to Live Text. Each change was individually reasonable, but the oscillation cost time and created noisy git history.

**Lesson:** For features that span multiple Apple frameworks (camera + OCR + UI), prototype the interaction model before committing to an implementation. The spec defined *what* the camera should do, but not *which Apple API* felt best. That's a judgment call that requires running the code.

### 4. Schema Migration Planning Could Have Started Earlier

We built migration infrastructure on Day 3 but didn't plan schema versions across specs. When specs 012 and 017 both needed new fields, the migrations were ad-hoc. A schema version roadmap in the constitution would have been cleaner.

**Lesson:** If your specs collectively modify a shared data model, maintain a migration timeline as a cross-spec artifact.

## Patterns to Steal

These are the reusable patterns from this project, independent of what the app does:

### The Constitution Template

```markdown
## Principle I — [Name]
[One paragraph describing the principle and when it applies]

## Principle II — [Name]
[...]

## Platform & Stack
- Target: iOS [version]
- Language: Swift [version]
- Build: [Xcode / SPM / XcodeGen]
- Persistence: [SwiftData / Core Data / etc.]

## Rules
- [Concrete rules that resolve common debates]
```

### The Background Processing Coordinator
`@MainActor @Observable` class with `Task` management, network awareness via protocol injection, and queue-based processing. [Code in Post 3](/blog/03-implementation-explosion.md).

### The NWPathMonitor → @Observable Bridge
Wraps callback-based APIs for SwiftUI consumption. Applicable to any Apple framework that uses closures on a DispatchQueue. [Code in Post 3](/blog/03-implementation-explosion.md).

### The WatchConnectivity Buffer
Queues messages until `WCSession` activation completes, then flushes with a dual-delivery strategy. [Code in Post 6](/blog/06-watch-spotlight-last-mile.md).

### Reactive Deduplication on iCloud Sync
Listen for `NSPersistentStoreRemoteChange`, score records by richness, merge duplicates. [Code in Post 5](/blog/05-icloud-sync-offline.md).

### Multi-Strategy Deep Link Router
Handle universal links, custom schemes, and Spotlight activities in a single `.onOpenURL` modifier with `@State`-based deferred navigation. [Code in Post 4](/blog/04-vision-siri-deep-links.md).

### SharedModelContainer with CloudKit Fallback
Try CloudKit + App Group first, fall back to App Group only. Graceful degradation for simulators and devices without iCloud. [Code in Post 2](/blog/02-specs-to-swift.md).

## The Workflow as a Transferable Practice

This project wasn't successful because of any single tool or framework. It was successful because the *process* — constitution → specify → clarify → plan → tasks → implement — forced decisions to happen at the right time.

Specifications before code. Clarifications before implementation. Principles before patterns.

You don't need Spec-Kit to do this. You don't need Claude Code. You need:
1. A set of principles written before the first line of code
2. Feature specs detailed enough to catch edge cases
3. An adversarial review process that asks "what about...?" before implementation
4. The discipline to spend 20–30% of your timeline on steps 1–3

The AI made implementation faster, but the specs made implementation *correct*. That's the insight that matters.

---

**Final tally:**
- 10 days
- 416 commits
- 25 feature specs
- ~15,000 lines of Swift
- 4 targets (iOS, watchOS, Widget, Share Extension)
- 1 constitution, 16 amendments
- 1 feature removed
- 0 regrets about spending 3 days on specs

---

*This is Part 7 of a 7-part series. [Read the series overview](/blog/README.md).*
