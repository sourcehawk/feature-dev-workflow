---
name: writing-docs
description:
  Use when a feature is structurally complete and its public-facing
  documentation (README, usage guide, tutorial, public API/reference) must
  be written or updated — before assuming the docs are done.
---

# writing-docs

## When to invoke

When a feature is structurally complete and a consumer of the project would need docs to use, understand, or extend what changed. Especially when:

- You just finished a feature and are about to call it shippable.
- You are about to write docs from memory and judge them done by re-reading your own draft.
- You are reaching for a diagram and about to hand-draw it in ASCII.

The scope test, in one question: **is this read by someone consuming the project, rather than an internal record of how it was decided or built?** If yes, and no other skill owns it, it belongs here.

## Core principle

**A doc is a set of answers to questions a reader arrives with.** You do not know the doc works until a reader who has *only the doc* can answer those questions.

You cannot be that reader. You carry the whole feature in your head, so the draft always "reads clearly" to you — that judgment is worthless for finding gaps. The reader who has only the page is the test. Same Iron Law as `superpowers:writing-skills`: **no doc change without a failing reader scenario first.**

## The loop

1. **Name the reader personas and their questions.** Who reads this, and the concrete questions each must answer or tasks each must complete. A doc often serves two at once — a newcomer who needs zero-to-working, and an experienced reader scanning for depth. Name each. The personas and their questions are the test.

2. **RED — run the reader, do not imagine it.** Dispatch a fresh subagent per persona, given *only* the current doc text — no codebase, no outside knowledge, no access to you — and that persona's questions. Record verbatim where it cannot answer, answers wrong, or guesses. "It reads clearly to me" and "a new reader could probably follow this" are not the test; an actual fresh reader failing a question is. If every persona answers everything, the change is not needed — stop.
   If you genuinely cannot dispatch a subagent, simulate the reader: answer each question using *only* the words on the page, nothing you know from building the feature. Treat that result as provisional — a real fresh-reader pass is still owed before the docs are called done. "Dispatch is unavailable" is never a license to fall back to judging your own draft.

3. **GREEN.** Write or update the doc to close exactly those gaps. A fresh subagent per persona, given only the new doc, answers all its questions and completes its task. The novice succeeds from the early sections; the advanced reader finds depth later; the advanced material does not block the novice. That ordering is progressive disclosure — proven by the test, not asserted.

4. **REFACTOR.** Cut anything that served no persona's question. Length is justified only by a question it answers. "Shorter" is never the goal; "no unearned content" is.

## Device and depth selection

A diagram, image, code block, or extra level of detail is never the default and never decoration. Each earns its place only by answering a reader's question better than prose would — and the fresh-reader test proves it did.

- **Diagram** — when the subject is a structure, flow, or relationship prose forces the reader to reassemble in their head (architecture, state machine, request lifecycle, decision flow). Use **Mermaid**, fenced as a ```` ```mermaid ```` block. It is not a dependency and needs no build step or asset hosting: GitHub, GitLab, and most markdown viewers render it natively from the source, and it diffs as text. **Do not hand-draw ASCII diagrams** — an ASCII box-and-arrow sketch is not a rendered diagram; it misaligns across fonts, rots on edit, and reviews badly. "ASCII renders fine in plain markdown" is the trap: it renders as the literal characters you typed, not as a diagram. If a reader answers the "how does X flow through Y" question from prose alone, the diagram was decoration; cut it.
- **Image** — only when the content is genuinely visual (a real screenshot, a rendered output) that Mermaid cannot express.
- **Code block** — when the reader's question is "how do I actually do this." A copyable, complete, runnable example beats a paragraph describing the call. One excellent example over many fragments. No example for a concept the reader only needs to understand, not invoke.
- **Depth** — calibrate per persona via progressive disclosure: accessible material first, deeper material below, ordered so depth never blocks the newcomer.

## Quality bar

The bar is **the documentation of a well-run open-source project**: precise, structured, assumes a competent reader, earns every sentence. No marketing fluff — superlatives ("blazing-fast", "seamless", "powerful"), feature-listing without telling the reader what they can now *do*, and adjectives standing in for an explanation all fail the bar.

## Out of scope

These are documentation, but other skills own them. Point there; do not duplicate.

- **Docstrings / code contracts** → `feature-dev-workflow:testing-a-feature` owns them as the contract its tests verify against.
- **Release notes / changelog "why"** → `feature-dev-workflow:drafting-a-release`.
- **Spec / ADR / plan** → `feature-dev-workflow:planning-a-feature`. These are internal records of how the work was decided and built, not consumer-facing.

## Anti-patterns

- **Calling docs done on the strength of your own read.** You wrote them, so they always read clearly to you; that is the one judgment that cannot find a gap. Until a reader who has only the page passes, you are guessing.
- **A diagram or section that answers no reader question.** Content that survives because it "looks thorough." If no persona's question needs it, the refactor step cuts it.
- **Hand-drawing a diagram in ASCII.** An ASCII sketch is not a rendered diagram — it misaligns and rots. Use Mermaid, or prose if the relationship does not need a picture.
- **Documenting an internal artifact, or re-documenting one another skill owns.** A spec, plan, or docstring written up here as public docs creates a second source of truth. Keep to consumer-facing docs; point at the owning skill for the rest.

## Red flags

| Thought | Reality |
|---------|---------|
| "It reads clearly to me" / "a new reader could probably follow this" | You hold the whole feature in your head. Run an actual fresh reader with only the doc; your read proves nothing. |
| "I'll write the docs from what I just built and check them myself" | Self-check is not the test. The reader who has only the page is. |
| "ASCII renders fine in plain markdown, no Mermaid dependency" | It renders as literal characters, not a diagram. Mermaid is not a dependency — GitHub renders it natively from source. Use a `mermaid` block. |
| "A diagram makes it look thorough" | Decoration fails the test. A diagram is only for a flow/structure prose can't carry. |
| "More detail is safer" | Unearned content buries the answer. Every section maps to a reader question or it's cut. |
