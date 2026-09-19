# ai-os-context

`ai-os-context` is the first memory-management layer for the GitHub-native AI OS.

It does **not** replace `GK-studio-JP/ai-bulletin-board`. The bulletin board remains the canonical append-only event journal. This repository deterministically replays that journal and emits small, non-authoritative projections for LLMs.

## Why

A worker should not need to re-read the complete protocol history, manager history, every open PR, and hundreds of comments just to resume one task.

The intended flow is:

```text
GitHub Issue + comments (canonical)
              |
              v
      deterministic replay
              |
              +--> task state projection
              +--> scheduler view
              +--> worker Context Capsule
                         |
                         v
                       LLM
```

The LLM receives the current state and exact source references, not the whole journal. If more detail is required, it can page in a referenced source explicitly.

## Invariants

1. GitHub Issue body + canonical Issue comments remain the source of truth.
2. Generated capsules and views are caches/projections, never authority.
3. Protocol ownership is computed by deterministic replay, not by an LLM.
4. `history_unsafe` fails closed.
5. The capsule never embeds full Issue-comment history.
6. A new LLM session must be able to reconstruct its execution state from GitHub-derived state.
7. Missing context is surfaced as a missing reference; it is not guessed.

## Compatibility

v0.1 implements the current `<!-- ai-bb:v1 -->` event envelope:

- `CLAIM`
- `HEARTBEAT`
- `RELEASE`
- `PROGRESS`
- `HANDOFF`
- `RESULT`
- `REVIEW`

Lease duration is fixed at 900 seconds.

## Optional task routing envelope

Existing bulletin-board Issues work without changes. New AI-OS tasks can optionally include this block in the Issue body:

````markdown
<!-- ai-os-task:v1 -->
```json
{
  "process": "PROC-AUTH",
  "repository": "GK-studio-JP/auth",
  "objective": "Fix JWT refresh race",
  "priority": 80,
  "contracts": ["CTR-AUTH-004", "CTR-STORAGE-002"],
  "context_refs": ["path:src/token/refresh.ts", "path:tests/auth-refresh.test.ts"],
  "acceptance": ["concurrency test passes"]
}
```
````

This envelope is routing/context metadata only. It does not alter `ai-bb:v1` ownership semantics.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

No third-party runtime dependencies are required.

## Live GitHub usage

Use a GitHub token with only the read permissions required for the repository:

```bash
export GITHUB_TOKEN=...

aios-context replay \
  --repo GK-studio-JP/ai-bulletin-board \
  --issue 123

aios-context capsule \
  --repo GK-studio-JP/ai-bulletin-board \
  --issue 123 \
  --process PROC-AUTH

aios-context scheduler-view \
  --repo GK-studio-JP/ai-bulletin-board
```

All commands write JSON to stdout by default. Use `--output file.json` when a durable projection is wanted.

## Offline usage

```bash
aios-context replay-files \
  --issue-file examples/issue.json \
  --comments-file examples/comments.json

aios-context capsule-files \
  --issue-file examples/issue.json \
  --comments-file examples/comments.json \
  --process PROC-AUTH
```

## Recommended first migration

Do not rewrite the bulletin board first.

1. Run `ai-os-context` as a read-only projection layer.
2. Change Worker boot to load a Context Capsule first.
3. Page in raw GitHub history only when the capsule says evidence is missing or unsafe.
4. Add Kernel/Scheduler repositories after the context reduction is proven.

See `docs/MIGRATION.md`.
