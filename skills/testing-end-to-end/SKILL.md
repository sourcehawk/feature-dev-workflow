---
name: testing-end-to-end
description:
  Use when a change is structurally complete and you're deciding
  whether — and what — end-to-end or system-level tests to add for a
  new user- or consumer-visible flow.
---

# testing-end-to-end

## When to invoke

When the structure has stopped moving and you're about to add tests that drive the whole system, not a single surface. Especially when:

- A feature is structurally complete — every sub-PR self-merged into the feature branch, the coherence sweep done — and you're at the integration checkpoint deciding system-level coverage.
- A change introduces a new flow a user or a downstream consumer can observe end to end.
- You're tempted to add an end-to-end test "now so it's ready" while pieces are still in flight.
- You're about to promote an edge case into the end-to-end suite because "it's only real when the full stack runs."

Skip when the change extends a flow an existing end-to-end test already covers, or when nothing user- or consumer-visible crosses more than one component. Those are unit and integration concerns.

**REQUIRED BACKGROUND:** `feature-dev-workflow:testing-a-feature`. The core principle — assert the contract, not the implementation — is identical here. This skill only moves the altitude: the contract is the user- or consumer-visible promise, and the surface under test is the system boundary.

## Core principle

**An end-to-end test asserts that a whole flow keeps the promise the user or consumer was made, exercising the real seams that unit tests stub out.**

That fixes both the timing and the selection:

- **Timing** follows from "whole flow." A flow you can test end to end only exists once its pieces are assembled. Until then there's no seam to exercise — only interfaces still being shaped.
- **Selection** follows from "the promise." The promise is a journey the user or consumer completes across components, not the contract of any single surface along the way. One end-to-end test per promised journey. Everything narrower is a lower-altitude test.

## When to write them

Write only after the feature is **structurally complete**: every sub-PR merged into the feature branch, the coherence sweep run, the structure settled. In the workflow that is the integration checkpoint (`feature-dev-workflow:reviewing-feature-progress` Step 6), not during implementation and not mid-fan-out.

Earlier is premature. An end-to-end test written while pieces are in flight either fails against a branch that doesn't have the flow yet, or pins itself to interfaces two unmerged worktrees are still changing. Both are fiction until the pieces land, and both generate churn when the real shapes differ. The per-component tests written test-first during implementation (`superpowers:test-driven-development`) are what give confidence in flight; the end-to-end test is what proves the assembled seam.

Write one only when the change introduces something **meaningful to assert end to end**: a new user- or consumer-visible flow, or a new golden path through the system. Not every feature earns a new end-to-end test. A feature that only extends a flow already covered may need none.

## What they should test

- **The golden path of each new flow.** Drive the system the way the user or consumer does, through the real entry point, with the real components wired together. Assert the promised outcome arrives. This single test proves the whole flow is wired.
- **The seams unit tests cannot see.** The value of an end-to-end test is the integration between components — data flowing from one step into the next, state transitioning across the boundary. That is precisely what every unit test mocks away.
- **Consumer-visible flow branches** that are part of the promise and cross the whole system — for example, an authorization boundary on a new externally-reachable entry point, where "the wrong caller is refused" is itself a promise to the consumer. One per branch, not one per permutation.

Only stub what you do not own, and stub it at its own boundary (the network, the external service's wire protocol). Everything you own runs for real. A test that mocks your own components is a unit test wearing an end-to-end costume: it skips the serialization, wiring, and parsing most likely to break, which is the whole reason to test end to end.

## What they should not test

- **Edge cases, boundary values, and single-component error branches.** Empty input, huge input, pagination, malformed data, off-by-one neighbors. These are fast, precise, and exhaustive at the unit level and slow, brittle, and incomplete at the end-to-end level. They belong in unit tests. See `feature-dev-workflow:testing-a-feature`.
- **A single surface's contract.** The serialized shape of one component's output, the mapping from an internal failure to an external error signal, input validation at one boundary. These are the contract of one surface and are tested at that surface's boundary, not by paying for a full-system round trip.
- **Anything already asserted at a lower level.** Re-asserting a unit-tested behavior through the full stack adds runtime and flake without adding signal. Respect the pyramid: many unit tests, fewer integration tests, few end-to-end tests.
- **Implementation and internal wiring.** Same as any test — an end-to-end test that breaks when an internal helper is renamed is coupled to implementation, not to the flow.

## Selection checklist

For each candidate end-to-end test, before writing it:

- [ ] **Is it a flow, or a single surface's contract?** A flow crosses components toward a user- or consumer-visible outcome. A surface's contract lives in one component. Only the flow is an end-to-end test.
- [ ] **Is the promise user- or consumer-visible?** If no user or downstream consumer can observe it, it is an internal detail. Test it where it lives.
- [ ] **Is it already covered below?** If a unit or integration test already asserts this, do not re-assert it end to end.
- [ ] **Does it exercise a real seam, or a mock?** If the components under test are mocked, it is not testing end to end. Stub only what you do not own.
- [ ] **Is the structure settled?** If pieces are still in flight, the flow does not exist yet. Wait.

## Anti-patterns

- **Edge-case promotion.** Moving empty/large/malformed/boundary cases into the end-to-end suite because "it's only real when the full stack runs." Observable-through-the-stack is not the same as belongs-in-end-to-end. If it is one component's behavior, test that component.
- **One end-to-end test per branch of a new entry point.** A new externally-reachable surface tempts wholesale coverage of all its branches end to end. Its branches are its contract — integration tests. End to end proves the journey, once per promised flow.
- **The mock-heavy fake.** Stubbing your own components to make the end-to-end test fast or to dodge a slow dependency. What's left tests the mocks, not the system.
- **Premature end-to-end tests.** Writing the flow test before the flow is assembled, against interfaces still being shaped. Wait for structural completion.
- **Suite bloat as confidence theater.** More end-to-end tests read as more confidence, but each one is slow and flake-prone. A bloated suite trains everyone to ignore its failures, which is worse than a small suite that is always trusted.

## Red flags

| Thought                                                          | Reality                                                                                                  |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| "This behavior is only real when the full stack runs, so it's an end-to-end test" | Observable-through-the-stack ≠ belongs-in-end-to-end. If it is one surface's contract, test it at that surface. |
| "It's a new public entry point, every branch needs an end-to-end test" | The branches are the entry point's contract — integration tests. End to end proves the flow once per promise. |
| "I'll write the end-to-end test now so it's ready when the pieces land" | The flow doesn't exist until the pieces are merged. You'd be pinning a test to interfaces still moving.   |
| "I'll mock the dependency so the end-to-end test is fast"        | Mock what you don't own, at its boundary. Mock your own components and it's a unit test in disguise.      |
| "More end-to-end tests means more confidence"                    | They're slow and brittle. A bloated suite gets its failures ignored. Fewer, higher-value, always-trusted. |
| "This edge case might slip through the unit tests"               | Then the unit test is the gap. Fix it there, where it's fast and precise — not by paying for a full round trip. |
