# Worker Bootstrap Core v0.1

This is intentionally small.

1. Identify the logical process you are executing for.
2. Load the current Context Capsule for the assigned task.
3. If `history_safe` is false, stop normal mutation and escalate.
4. Confirm the task belongs to this process or request routing correction.
5. Page in only the contracts/files/artifacts required for the next action.
6. Never infer another process's internals from incomplete context.
7. Before an ownership-sensitive write, refresh canonical GitHub state.
8. Emit durable PROGRESS/HANDOFF/RESULT evidence; do not rely on chat memory.
