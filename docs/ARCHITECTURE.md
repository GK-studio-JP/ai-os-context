# Architecture

## Role in the AI OS

`ai-os-context` is the memory-management / projection layer.

```text
                  canonical
GitHub Issue/comments --------------+
                                     |
                                     v
                            +-----------------+
                            | ai-os-context   |
                            | Replay Engine   |
                            | Context Compiler|
                            +--------+--------+
                                     |
                   +-----------------+----------------+
                   |                 |                |
                   v                 v                v
             Worker Capsule     Scheduler View   Kernel View (later)
```

The output is intentionally disposable. Rebuild it whenever the canonical journal changes.

## Disk vs memory

- **Disk / event journal:** full GitHub Issue and comment history.
- **Page table:** immutable refs such as comment IDs, commit SHAs, PR exact heads, repository paths.
- **Process memory:** repository-specific rules/architecture loaded only for the target process.
- **Thread memory:** one task capsule plus its latest checkpoint/handoff.
- **Page fault:** required fact is absent; fetch the referenced source instead of guessing.

## Why replay is code, not LLM reasoning

Ownership, 15-minute lease expiry, idempotency, RELEASE, RESULT, and deterministic comment ordering are protocol mechanics. They are cheaper and safer to evaluate in ordinary code. The LLM should reason about the task, not recompute the operating system.

## Trust boundary

A capsule is not proof by itself. Before a write that depends on ownership, re-fetch and replay canonical GitHub state.

This repository starts read-only on purpose.
