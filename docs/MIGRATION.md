# Migration from current ai-bulletin-board operation

## Phase 0 — no semantic changes

Keep `ai-bulletin-board` unchanged as the canonical journal.

Run `ai-os-context` externally and compare its replay output with the existing Pages projection / human interpretation.

Acceptance gate:

- CLAIM winner matches current protocol.
- lease expiry matches protocol v1.
- RELEASE and RESULT match current protocol.
- edited protocol comments fail closed.
- duplicate idempotency keys are deterministic.

## Phase 1 — Context Capsule first boot

Change only the worker boot sequence:

```text
OLD
rules -> manager history -> issue full history -> PRs -> replay -> work

NEW
core rule ABI -> Context Capsule -> referenced page-in -> work
```

Raw Issue history remains available as a page-in fallback, but is not loaded by default.

## Phase 2 — optional task envelope

New tasks may add `<!-- ai-os-task:v1 -->` metadata for process/routing/context refs. Old tasks continue to work.

## Phase 3 — scheduler projection

Give the Scheduler LLM only `ai-os-scheduler-view:v1`, plus the scheduler's own local rules. Do not send source code or unrelated Issue histories to the scheduler.

## Phase 4 — kernel/scheduler repositories

After the context reduction is proven, split policy/authority into `ai-os-kernel` and dispatch into `ai-os-scheduler`.

## Rollback

Because every output here is non-authoritative, rollback is simply: stop consuming the projection and return to direct canonical replay. No bulletin-board data migration is required.
