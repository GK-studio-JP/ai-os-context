# v0.1 limitations

- Scheduler view currently fetches comments for each selected Issue. This moves token cost out of the LLM but can still consume GitHub API quota. Add ETag/incremental replay before very large-scale use.
- Ordinary Issue comment APIs expose edit timestamps but cannot prove that no comment was historically deleted. v0.1 follows the protocol's evidence-based rule: it fails closed on an edit it can prove and does not invent deletion evidence.
- Context Capsule selection is reference-based, not semantic code search. Repository-specific retrieval/page-in is the next layer.
- `ai-os-task:v1` is optional and local to this repository. It must not silently redefine `ai-bb:v1`.
- Kernel View is intentionally not implemented yet; the first goal is reducing Worker/Scheduler context without changing coordination authority.
