# Migration from current ai-bulletin-board operation

The canonical coordination journal remains `GK-studio-JP/ai-bulletin-board`. `ai-os-context` is a read-only replay/projection layer: none of its generated files can grant ownership, authorization, or completion.

## Phase 0 — no semantic changes

Keep the bulletin board unchanged as the canonical journal.

Run `ai-os-context` against the live Issues and compare deterministic replay with the existing protocol behavior.

Acceptance gate:

- CLAIM winner matches `ai-bb:v1`.
- lease expiry matches protocol v1.
- RELEASE and RESULT match protocol v1.
- edited canonical protocol comments fail closed as `history_unsafe`.
- duplicate idempotency keys replay deterministically.
- no generated projection is treated as authority.

## Phase 1 — Context Capsule first boot

Change only the Worker boot sequence:

```text
OLD
rules -> manager history -> full Issue history -> PRs -> replay -> work

NEW
core rule ABI -> task Context Capsule -> referenced page-in -> work
```

The default Worker context should contain the selected task capsule, not the whole bulletin-board history.

Raw Issue comments, PRs, source files, and contracts remain available through explicit page-in when the capsule reports a missing reference or `history_unsafe`.

Before CLAIM, HEARTBEAT, RELEASE, RESULT, or another ownership-sensitive mutation, refresh the canonical Issue state. A capsule is a boot image, not a lock.

Acceptance gate:

- a fresh LLM session can resume from the capsule plus referenced sources;
- unrelated task histories are absent from the default Worker context;
- missing evidence is requested instead of guessed;
- stale capsules cannot authorize mutation.

## Phase 2 — explicit task routing

New tasks may add `<!-- ai-os-task:v1 -->` metadata for process, target repository, priority, contracts, capabilities, context refs, and acceptance criteria.

Legacy Issues remain valid. During migration they can be routed explicitly with:

```bash
--default-process PROC-BULLETIN
```

Issues with neither an envelope process nor an explicit fallback are reported as `unrouted`; they do not silently enter the runnable queue.

The routing envelope is metadata only. It does not change `ai-bb:v1` ownership semantics.

## Phase 3 — bounded Scheduler projection

Scheduler boot should consume `ai-os-scheduler-view:v1` rather than source repositories or full Issue histories.

A live boot image can be generated with:

```bash
aios-context snapshot \
  --repo GK-studio-JP/ai-bulletin-board \
  --state open \
  --default-process PROC-BULLETIN \
  --output-dir projection
```

The projection contains:

```text
projection/
├── README.md
├── manifest.json
├── scheduler-view.json
└── capsules/
    └── issue-N.json
```

Scheduler boot rule:

1. Read `scheduler-view.json`.
2. Choose from `runnable`; never schedule `unrouted`, blocked, or `history_unsafe` rows.
3. Pass only the selected task's capsule to the Worker.
4. Page in canonical evidence only when required.
5. Refresh canonical state before ownership-sensitive mutation.

The Scheduler may use priority and dependency metadata to decide what runs next, but it must not infer subsystem implementation details from unrelated repositories.

Acceptance gate:

- scheduler projection is bounded and contains no unrelated source code;
- `unrouted` is explicit;
- `history_unsafe` fails closed;
- manifest and scheduler view share the same generation timestamp;
- every manifest capsule path resolves and its fingerprint is recorded.

## Phase 3.1 — disposable projection artifact

`.github/workflows/snapshot.yml` maintains the projection as a disposable GitHub Actions artifact.

Current operation:

- manual `workflow_dispatch`;
- hourly refresh at minute 17;
- refresh on relevant source/test/workflow changes;
- source repository defaults to `GK-studio-JP/ai-bulletin-board`;
- legacy fallback defaults to `PROC-BULLETIN`;
- validation runs before upload;
- artifact name is `ai-os-projection`;
- retention is seven days.

Do not commit generated projection state back into the authoritative journal. If cross-repository reads later require credentials beyond the run's `github.token`, use a read-only `AIOS_GITHUB_TOKEN`.

## Phase 4 — Kernel/Scheduler repositories

After the context reduction is proven in production-like runs, split control-plane responsibilities:

```text
Kernel LLM
  -> authority, capabilities, process registry, IPC/syscalls

Scheduler LLM
  -> runnable projection, dependency/order/CPU allocation

Repository Agent
  -> subsystem-local decisions

Worker LLM
  -> one bounded task execution
```

The Kernel must not absorb subsystem implementation logic, and the Scheduler must not become an authority service.

## Rollback

Every output produced by `ai-os-context` is non-authoritative. Rollback is therefore:

1. stop consuming the projection artifact;
2. return Worker/Scheduler boot to direct canonical replay;
3. leave bulletin-board data untouched.

No canonical data migration is required to roll back.
