# ai-os-context

`ai-os-context` is the memory-management and projection layer for the GitHub-native AI OS.

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
2. Generated capsules, scheduler views, manifests, and workflow artifacts are caches/projections, never authority.
3. Protocol ownership is computed by deterministic replay, not by an LLM.
4. `history_unsafe` fails closed.
5. The capsule never embeds full Issue-comment history.
6. A new LLM session must be able to reconstruct its execution state from GitHub-derived state.
7. Missing context is surfaced as a missing reference; it is not guessed.
8. Ownership-sensitive mutation must refresh canonical GitHub state before acting.

## Context budget and provenance

Context Capsules are non-authoritative projections with a default budget of 20,000 rendered JSON characters. The budget is deterministic: it is measured from pretty JSON with sorted keys.

Each capsule includes a `context_budget` object with the configured limit, rendered size, truncation/enforcement state, and `omitted_paths`. It also carries `source.source_refs` plus a full SHA-256 `source.source_fingerprint` for the Issue + replay projection boundary. These lineage fields help detect a changed projection input; they do not replace canonical GitHub state.

When a capsule exceeds its budget, reduction is limited to non-authoritative contextual material such as context references, contracts, acceptance details, execution artifacts, and long descriptive text. Authority, capabilities, blockers, source metadata, and replay state are preserved. The capsule then sets `context_budget.truncated=true`, `memory.page_in_required=true`, and adds `context_budget` to `memory.missing` so the worker must explicitly page in omitted evidence instead of guessing.

The `capsule`, `capsule-files`, and `snapshot` commands accept `--max-chars`. The minimum supported limit is 4096 characters; the default is 20000.

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
  "repository": "owner/auth",
  "objective": "Fix JWT refresh race",
  "priority": 80,
  "contracts": ["CTR-AUTH-004", "CTR-STORAGE-002"],
  "context_refs": ["path:src/token/refresh.ts", "path:tests/auth-refresh.test.ts"],
  "acceptance": ["concurrency test passes"]
}
```
````

This envelope is routing/context metadata only. It does not alter `ai-bb:v1` ownership semantics.

Scheduler rows with no process are reported as `unrouted` instead of silently becoming runnable. During migration, `--default-process` can explicitly provide a fallback for legacy Issues. The current bulletin-board projection uses `PROC-BULLETIN` as that fallback.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

No third-party runtime dependencies are required.

## Live GitHub usage

Use a GitHub token with only the read permissions required for the source repository:

```bash
export GITHUB_TOKEN=...

aios-context replay \
  --repo GK-studio-JP/ai-bulletin-board \
  --issue 123

aios-context capsule \
  --repo GK-studio-JP/ai-bulletin-board \
  --issue 123 \
  --process PROC-BULLETIN

aios-context scheduler-view \
  --repo GK-studio-JP/ai-bulletin-board \
  --default-process PROC-BULLETIN
```

The replay, capsule, and scheduler-view commands write JSON to stdout by default. Use `--output file.json` when a durable local projection is wanted.

## Bounded projection snapshot

The `snapshot` command materializes one bounded boot image for Scheduler/Worker experiments:

```bash
aios-context snapshot \
  --repo GK-studio-JP/ai-bulletin-board \
  --state open \
  --default-process PROC-BULLETIN \
  --output-dir projection
```

The generated directory contains:

```text
projection/
├── README.md
├── manifest.json
├── scheduler-view.json
└── capsules/
    ├── issue-123.json
    └── issue-124.json
```

Boot rule:

1. Read `scheduler-view.json` first.
2. Select one runnable task.
3. Load only that task's `capsules/issue-N.json`.
4. Page in canonical GitHub evidence only when the capsule reports missing context or unsafe history.
5. Refresh canonical GitHub state before any ownership-sensitive mutation.

`manifest.json` records the capsule path and fingerprint for every projected task. All files under `projection/` are explicitly non-authoritative.

## GitHub Actions artifact

`.github/workflows/snapshot.yml` builds the live projection:

- manually through `workflow_dispatch`;
- hourly at minute 17;
- on pushes that change `src/**`, `tests/**`, or the snapshot workflow itself.

The workflow defaults to `GK-studio-JP/ai-bulletin-board`, open Issues, and `PROC-BULLETIN`. It validates the manifest, scheduler view, and every referenced capsule before uploading `projection/` as the `ai-os-projection` artifact for seven days.

If the source repository later requires credentials not available to the run's `github.token`, configure a repository secret named `AIOS_GITHUB_TOKEN` with read-only access to that source.

The workflow does not commit projection output back to `main`; the artifact remains a disposable cache.

## Offline usage

```bash
aios-context replay-files \
  --issue-file examples/issue.json \
  --comments-file examples/comments.json

aios-context capsule-files \
  --issue-file examples/issue.json \
  --comments-file examples/comments.json \
  --process PROC-BULLETIN
```

## Recommended first migration

Do not rewrite the bulletin board first.

1. Run `ai-os-context` as a read-only projection layer.
2. Change Worker boot to load a Context Capsule first.
3. Change Scheduler boot to consume `scheduler-view.json` instead of scanning implementation repositories.
4. Page in raw GitHub history only when the capsule says evidence is missing or unsafe.
5. Keep projection artifacts disposable and refresh canonical state before mutation.
6. Add Kernel/Scheduler repositories after the context reduction is proven.

See `docs/MIGRATION.md`.
