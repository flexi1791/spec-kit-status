# Days 1–2: The Constitution Before the Code

*Part 1 of "10 Days, 400 Commits: Building a Multi-Target iOS 26 App with AI-Driven Spec Development"*

---

We wrote 12 feature specifications before a single line of Swift. Here's why that was the fastest decision of the entire project.

## The Setup

The idea was simple: build a full-featured iOS 26 app — with an Apple Watch companion, home screen widgets, a share extension, Siri integration, Spotlight search, and iCloud sync — in about ten days. Not a prototype. Not a hackathon demo. A real, production-quality app with offline-first architecture, strict concurrency, and a clean data model.

The tool: [Claude Code](https://claude.ai/code), Anthropic's CLI agent for software engineering, paired with [Spec-Kit](https://github.com/nicklama/spec-kit), a specification-driven development workflow that gives the AI (and you) a structured process for turning ideas into shipping code.

The catch: if you just start prompting an AI to "build me an app," you get a mess. You get files that contradict each other, patterns that drift, and architectural decisions that were never actually decided — they just happened. We'd seen this before and knew the fix wasn't "prompt better." The fix was *spec first*.

## What Is Spec-Kit?

Spec-Kit is a set of slash commands and templates that enforce a deliberate workflow:

```
constitution → specify → clarify → plan → tasks → implement
```

Each step produces a Markdown artifact that lives in the repo alongside the code. Nothing is ephemeral. Every decision is traceable. Here's what each step does:

1. **Constitution** — Project-wide principles that apply to *every* feature. Think of it as your architectural decision record, but written before the architecture exists.
2. **Specify** — A detailed feature spec: user scenarios, requirements, success criteria, data model implications.
3. **Clarify** — An adversarial review of the spec. The AI asks up to 5 targeted questions about ambiguities, edge cases, and scope gaps. Your answers get encoded back into the spec.
4. **Plan** — An implementation plan with file paths, function signatures, and dependency ordering.
5. **Tasks** — A checklist of discrete, ordered implementation steps.
6. **Implement** — Code generation from the task list, one task at a time.

The key insight: **each step constrains the next**. The constitution constrains every spec. Every spec constrains its plan. Every plan constrains its tasks. By the time you reach implementation, most decisions are already made.

## Day 1: Ratifying the Constitution

Before writing a single spec, we defined nine principles that would govern every line of code:

```markdown
## Principle I — SwiftUI-First
All user-facing UI is built with SwiftUI. UIKit or AppKit may be used
only when no SwiftUI equivalent exists (e.g., camera capture via
AVCaptureSession). Any UIKit usage must be wrapped in a
UIViewControllerRepresentable.

## Principle II — Privacy by Default
User data lives on-device by default. Network calls happen only when
the user explicitly triggers enrichment. iCloud sync transmits data
only to the user's own devices and does not require an opt-in prompt.

## Principle III — Offline-First
The app must be fully functional without a network connection.
Network-dependent features degrade gracefully and queue work for
when connectivity returns.
```

There were six more — covering separation of models and views, design fidelity, simplicity, lean code, test-driven development (Swift Testing only, never XCTest), and constructive error handling. Each principle was specific enough to resolve real implementation debates later:

- *"Should we add a loading spinner for this API call?"* — Principle III says the app must work offline. The data should already be there. The spinner is for enrichment, not core functionality.
- *"Should we use a coordinator pattern or just @Observable?"* — Principle VII says lean, idiomatic code. No unnecessary abstractions. `@Observable` it is.
- *"Should we catch this error silently?"* — Principle IX says every error must carry full diagnostic context. No silent catches. `#if DEBUG` print blocks on every catch.

The constitution was versioned. By the end of the project it had gone through 16 revisions (v1.0.0 → v1.16.0), with amendments added as implementation revealed gaps. But the core principles never changed. They were right from the start because we spent time on them before we were distracted by code.

## Day 1: The First Three Specs

With the constitution ratified, we created three foundational specs:

| Spec | Feature | Why First |
|------|---------|-----------|
| 001 | Core data model and list view | Everything depends on the data model |
| 002 | Photo-based input (camera + OCR) | Primary input method, shapes the add-item pipeline |
| 003 | Category management | Defines the taxonomy that every item references |

Each spec followed the same template:

```markdown
# Feature Specification: [Name]

## Overview
[One paragraph describing the feature and its purpose]

## User Scenarios
[Concrete usage narratives, not abstract requirements]

## Functional Requirements
[FR-001 through FR-NNN, each testable and specific]

## Data Model Implications
[What changes to the SwiftData schema, if any]

## Dependencies
[Which other specs must be implemented first]

## Success Criteria
[How we know this feature is done]
```

The user scenarios were critical. Not "the user can add an item" but "the user opens the app, taps +, types a title, selects a category from an icon grid, and sees the new item appear at the top of the list with a placeholder image." This level of detail caught UX edge cases before they became code bugs.

## Day 2: The Specification Explosion

Day 2 started with a question: *"What else does this app need to feel complete?"*

The answer was nine more specs, created in rapid succession:

| Spec | Feature | Motivation |
|------|---------|------------|
| 004 | Onboarding | First-run experience, category selection, permission grants |
| 005 | Filter, search & share | Users will want to find and share their data |
| 006 | Offline resilience | Constitution Principle III demands it |
| 007 | Detail & edit screen | Every list needs a detail view |
| 008 | Settings | User preferences, account info |
| 009 | App navigation | Tab structure, deep link routing, launch phases |
| 010 | API security | Server-side proxy for third-party API keys |
| 011 | Voice input | Microphone-based input using on-device ML |
| 012 | Data enrichment pipeline | API lookup, metadata resolution, image fetch |

By end of day 2, we had **12 feature specs** — the full vision of the app, expressed as structured Markdown, before writing any Swift.

### Why This Matters

Here's what we *didn't* do: we didn't open Xcode. We didn't create a project. We didn't write `struct ContentView: View`. We didn't debate whether to use MVVM or MVC or VIPER. We didn't bikeshed the folder structure.

Instead, we had:
- A constitution that would settle every architectural debate
- 12 specs that defined every feature, its requirements, and its dependencies
- A dependency graph showing which specs needed to be implemented first
- Data model implications tracked across specs (spec 001 owns the core model, spec 003 owns categories, spec 012 owns the enrichment pipeline)

This took two days. It felt slow. It was the fastest decision of the project.

## The Clarification Sessions

Before any spec could be planned, it went through `/speckit.clarify`. This is where the AI reads the spec, identifies underspecified areas, and asks up to 5 targeted questions. Your answers are encoded directly back into the spec.

Here's a real example from Spec 009 (App Navigation):

> **Q: What happens when the app receives a universal link while the user hasn't completed onboarding?**
>
> A: The link is stored as a pending deep link. After onboarding completes, the app navigates to the linked content.

This single Q&A prevented a bug that would have taken hours to debug later. Without it, deep links received during onboarding would have been silently dropped.

Another example from Spec 007 (Detail Screen):

> **Q: Can the user edit the title of an item after it's been saved and enriched with metadata?**
>
> A: No. The title is locked after save. The user can edit notes, category, and completion status, but not the title. This prevents orphaning the enrichment data.

Every spec went through clarification on Day 3 (covered in the next post). But the specs created on Days 1–2 were already detailed enough that clarification refined them rather than rewriting them.

## What We Learned

**Specification-driven development with AI is not about generating more code faster.** It's about making *decisions* faster — and making them once, in a structured artifact, instead of scattered across fifty prompts.

The constitution prevented scope creep. When someone (us) inevitably asked "should we add a recommendation engine?", the answer was already written: *Principle VI — Simplicity. YAGNI. Build only what the spec requires.*

The specs prevented contradictions. When spec 005 (sharing) and spec 021 (universal links) both needed to define a share payload format, the dependency was visible in the spec graph. We defined it once, in spec 005, and spec 021 referenced it.

The clarification sessions prevented bugs. Not all bugs — we still had plenty. But the category of "I didn't think about that case" bugs was almost eliminated.

**Total at end of Day 2:**
- 12 feature specs
- 1 constitution (v1.0.0)
- 0 lines of Swift
- 94 commits (all Markdown)

Next up: [Day 3 — translating specs into Swift, SwiftData schema design, and package architecture](/blog/02-specs-to-swift.md).

---

*This is Part 1 of a 7-part series. [Read the series overview](/blog/README.md).*
