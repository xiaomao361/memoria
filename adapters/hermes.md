# Hermes Adapter

Hermes should use Memoria through bounded CLI calls.

## Recommended Trust Model

On this device, Hermes is a trusted local agent and can write durable memories
directly when the content is verified or clearly attributable.

```text
source-agent: hermes
trust-level: trusted_writer
can-write-durable: true
```

Use the candidate queue only for uncertain synthesis, external outputs, or
content that still needs user/Codex review.

## Durable Write

```bash
conda run -n zhouwei python3 cli.py agent-store \
  --agent-id hermes \
  --content "..." \
  --tags "..." \
  --source hermes \
  --kind fact \
  --authority confirmed
```

## Recall

```bash
conda run -n zhouwei python3 cli.py agent-recall \
  --agent-id hermes \
  --query "..."
```

## Hermes Use Rules

- Prefer structured outputs that Codex or the user can validate.
- Durable writes are allowed for this device's local trusted agents.
- Use candidates when the content is speculative, delegated, or not yet
  validated.
- Do not request private recall unless the task explicitly requires it and the
  user has authorized it.
- Include source task/run context in content when adding memories or candidates.
- Lara writes through Hermes on this device, so use `agent-id hermes`,
  `source=hermes`, and `source_agent=hermes` in durable records.
