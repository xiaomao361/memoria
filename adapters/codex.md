# Codex Adapter

Codex should treat Memoria as an external shared memory service, not as a Codex
native private memory store.

## Runtime

```text
MEMORIA_ROOT=/Users/zhouwei/.claracore/memoria
```

## Current Command Pattern

Use the repository CLI until a Codex-native wrapper exists:

```bash
conda run -n zhouwei python3 cli.py recall --query "..."
```

Durable writes should include provenance:

```bash
conda run -n zhouwei python3 cli.py store \
  --content "..." \
  --tags "..." \
  --source codex \
  --kind fact \
  --authority confirmed \
  --retrieval-role background \
  --source-agent codex
```

## Codex Use Rules

- Recall when prior project decisions or user preferences are likely relevant.
- Store only concise durable facts, decisions, migration records, and verified
  project state.
- Do not store raw command output.
- Local device agents are trusted writers; use candidates for uncertain
  synthesis, external outputs, or content that still needs review.
- Use `source=codex` and `source_agent=codex` for durable writes.
- Keep Codex's own `.codex/memories` separate from Memoria.
