# 10 Days, 400 Commits

**Building a Multi-Target iOS 26 App with AI-Driven Spec Development**

A 7-part practitioner's journal on shipping an iOS app, Apple Watch companion, home screen widgets, share extension, and Siri integration using Claude Code and specification-driven development with Spec-Kit.

---

## The Series

1. **[Days 1–2: The Constitution Before the Code](01-constitution-before-code.md)**
   Writing 12 feature specs before a single line of Swift — and why that was the fastest decision.

2. **[Day 3: From Specs to Swift](02-specs-to-swift.md)**
   SwiftData schema design, package architecture, and the clarification surge that prevented a week of rework.

3. **[Day 4: 81 Commits — The Implementation Explosion](03-implementation-explosion.md)**
   When specs are solid, implementation becomes mechanical. Background processing, widgets, and network monitoring patterns.

4. **[Days 5–6: Vision OCR, Siri App Intents, and Deep Linking](04-vision-siri-deep-links.md)**
   Camera input, voice commands, universal links, and the feature that didn't survive (voice dictation).

5. **[Days 7–8: iCloud Sync, Deduplication, and Offline Resilience](05-icloud-sync-offline.md)**
   Making SwiftData + CloudKit reliable, reactive deduplication, and constructive error handling.

6. **[Days 9–10: Apple Watch, Spotlight, and the Last Mile](06-watch-spotlight-last-mile.md)**
   WatchConnectivity buffering, CoreSpotlight indexing, share extensions, and cross-platform gotchas.

7. **[Retrospective: What Worked, What Didn't, What to Steal](07-retrospective.md)**
   Honest metrics, reusable patterns, and why the slow days made the fast days possible.

---

## Quick Stats

| Metric | Value |
|--------|-------|
| Calendar days | 10 |
| Total commits | 416 |
| Feature specs | 25 |
| Lines of Swift | ~15,000 |
| Targets | 4 (iOS, watchOS, Widget, Share Extension) |
| Constitution revisions | 16 |
| Features removed | 1 |

## Tools Used

- **[Claude Code](https://claude.ai/code)** — Anthropic's CLI agent for software engineering
- **[Spec-Kit](https://github.com/nicklama/spec-kit)** — Specification-driven development workflow
- **Xcode 26** + **XcodeGen** — Build and project management
- **Swift 6.2** with strict concurrency

## Reusable Patterns

Each post includes production-quality code snippets for common iOS patterns:

- Background processing coordinator with network awareness (Post 3)
- NWPathMonitor bridged to @Observable (Post 3)
- WidgetKit timeline provider with shared SwiftData container (Post 3)
- Vision OCR pipeline with iOS 18+ API (Post 4)
- Siri App Intents with SwiftData @Dependency injection (Post 4)
- Multi-strategy deep link router (Post 4)
- Reactive iCloud deduplication (Post 5)
- StoreKit review prompt eligibility service (Post 5)
- WatchConnectivity with message buffering (Post 6)
- CoreSpotlight indexing with domain identifiers (Post 6)
- Share extension → host app handoff (Post 6)
- SharedModelContainer with CloudKit fallback (Post 2)
- SwiftData VersionedSchema pattern for Swift 6.2 (Post 2)
- Swift Testing patterns for SwiftData (Post 2)
