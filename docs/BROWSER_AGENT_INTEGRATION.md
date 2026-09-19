# Browser Agent integration

Treat `browser-agent` as an external device/driver, not as AI-OS process memory.

The browser handoff architecture uses a GitHub Issue as a command/response queue, GitHub Actions as the execution environment, and a sequential observe -> one action -> re-observe loop. That transport can coexist with `ai-bulletin-board`, but browser command history should not be loaded into every worker Context Capsule.

Recommended capsule representation:

```json
{
  "device": "browser-agent",
  "session_ref": "Issue:#16",
  "state": "ready",
  "last_observation_ref": "comment:123456",
  "next_action": "getPage"
}
```

Only page in the browser observation needed for the next operation.

Rules:

- Do not copy tokens/cookies/secrets into capsules.
- Do not treat browser Issue comments as canonical AI-OS task ownership events unless they also conform to the bulletin-board protocol.
- Keep browser session identity separate from task ownership identity.
- Prefer session-scoped routing when multiple browser sessions can exist.
- A future direct MCP transport should change the driver, not the Context Capsule ABI.
