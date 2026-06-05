# QClaw / OpenClaw Adapter

Compatibility executable skill:

```text
/Users/zhouwei/.qclaw/skills/memoria/
```

Shared runtime:

```text
/Users/zhouwei/.claracore/memoria/
```

Compatibility path:

```text
/Users/zhouwei/.qclaw/memoria -> /Users/zhouwei/.claracore/memoria
```

## Commands

Stats:

```bash
conda run -n zhouwei python3 /Users/zhouwei/.qclaw/skills/memoria/cli.py stats
```

Recall:

```bash
conda run -n zhouwei python3 /Users/zhouwei/.qclaw/skills/memoria/cli.py recall --limit 5
```

Store:

```bash
conda run -n zhouwei python3 /Users/zhouwei/.qclaw/skills/memoria/cli.py store \
  --content "..." \
  --tags "..." \
  --source clara \
  --source-agent clara
```

## Notes

QClaw/OpenClaw can keep using the existing skill path, but that path is a
symlink to the ClaraCore executable skill root. Runtime data has already moved
to ClaraCore through the Memoria data symlink.

Clara should use `source=clara` and `source_agent=clara` for durable writes.
