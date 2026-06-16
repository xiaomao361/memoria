# Memoria Shared Agent Memory Implementation Plan

> ⚠️ **历史文档** (2026-05-28)。本文描述的 candidate 审核流、agent trust policy、
> recall-context 结构化上下文已于 v6.9.1 (2026-06-16) 移除。
> 保留此文档仅作设计决策记录，不代表当前可用功能。
> 当前功能请参考 README.md 和 SKILL.md。

Date: 2026-05-28

## Goal

Evolve Memoria from a searchable personal memory store into a shared long-term memory substrate for multiple agents.

The product boundary should stay clear:

- Memoria is the memory engine.
- Higher-level workspaces such as Continuum can orchestrate tasks, agents, artifacts, and workflows later.

Memoria should focus on reliable storage, governance, structured recall, lifecycle management, and agent-safe APIs.

## Operating Assumption

Multiple agents will read from and write to the same memory system.

That means Memoria must support:

- Shared memory with source attribution.
- Agent identity on writes and reads.
- Review before untrusted agent output becomes durable memory.
- Explicit memory type and lifecycle state.
- Permission-aware private memory.
- Recall output that agents can use without guessing how each item should be treated.

## Current Baseline

Current Memoria v6 already has:

- Markdown-backed memory files.
- SQLite metadata and FTS.
- ChromaDB vector search with Ollama embeddings.
- Tags and links as labels.
- Private/public separation.
- Importance and archive fields.
- Basic governance commands such as dormant, suggest-merge, and suggest-conflicts.
- FastAPI and CLI access.

The next work should extend these foundations instead of replacing them.

## Six Implementation Tracks

### 1. Memory Quality Governance

Problem:

Long-term shared memory becomes polluted if duplicate, stale, conflicting, low-value, or untrusted memories are treated the same as clean durable memories.

Target capabilities:

- Detect duplicate memories.
- Detect conflicts.
- Detect stale memories.
- Detect likely low-value transient memories.
- Recompute importance using multiple signals.
- Provide review queues for governance decisions.

Suggested implementation:

- Extend existing maintenance code rather than creating a separate governance subsystem immediately.
- Add governance issue records to SQLite.
- Keep issue detection deterministic where possible.
- Allow LLM-assisted classification later, but do not make core maintenance depend on it.

Suggested schema:

```sql
CREATE TABLE IF NOT EXISTS governance_issues (
  id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  related_memory_id TEXT,
  issue_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL DEFAULT 'open',
  reason TEXT,
  evidence_json TEXT,
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  resolved_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_governance_issues_memory
ON governance_issues(memory_id);

CREATE INDEX IF NOT EXISTS idx_governance_issues_status
ON governance_issues(status, issue_type);
```

Issue types:

- `duplicate`
- `conflict`
- `stale`
- `low_value`
- `missing_type`
- `private_risk`
- `source_untrusted`

CLI/API candidates:

- `memoria maintain governance`
- `GET /api/governance/issues`
- `POST /api/governance/issues/{id}/resolve`

### 2. Memory Type And Semantic Role

Problem:

All memories are currently mostly text plus metadata. For agent use, the system needs to know whether a memory is a fact, preference, decision, event, project state, person context, idea, artifact summary, todo, or technical note.

Target capabilities:

- Add `kind` to memories.
- Add `authority` to separate fact, user preference, confirmed decision, hypothesis, draft, model-generated output, and agent observation.
- Add `retrieval_role` so recall can mark an item as background, hard constraint, reference, prior judgment, current state, example, or forbidden direction.

Suggested memory kinds:

- `fact`
- `preference`
- `decision`
- `event`
- `project_state`
- `person_context`
- `idea`
- `artifact_summary`
- `todo`
- `technical_note`
- `conversation_summary`
- `agent_observation`

Suggested authority values:

- `confirmed`
- `user_preference`
- `user_decision`
- `observed`
- `inferred`
- `model_generated`
- `draft`

Suggested retrieval roles:

- `background`
- `hard_constraint`
- `reference`
- `prior_judgment`
- `current_state`
- `example`
- `forbidden_direction`

Suggested schema changes:

```sql
ALTER TABLE memories ADD COLUMN kind TEXT DEFAULT 'fact';
ALTER TABLE memories ADD COLUMN authority TEXT DEFAULT 'confirmed';
ALTER TABLE memories ADD COLUMN retrieval_role TEXT DEFAULT 'background';
ALTER TABLE memories ADD COLUMN confidence REAL DEFAULT 1.0;
```

File front matter should preserve these fields:

```yaml
kind: decision
authority: user_decision
retrieval_role: hard_constraint
confidence: 1.0
```

Backfill strategy:

- Default old records to `kind=fact`, `authority=confirmed`, `retrieval_role=background`.
- Add a classifier command later to suggest better values.
- Do not auto-rewrite all old files until the mapping is validated.

### 3. Structured Context Recall

Problem:

Agents should not receive a flat list of "related memories". They need structured context that explains how each item should be used.

Target capabilities:

- Add a structured recall endpoint.
- Group recalled memories by role.
- Include provenance and confidence.
- Exclude stale, discarded, archived, private, or low-confidence items unless requested.
- Mark hard constraints and forbidden directions clearly.

Suggested API:

```http
POST /api/recall/context
```

Request:

```json
{
  "query": "plan next step for Hermes token consumption work",
  "agent": "hermes",
  "scope": {
    "project": "mimo token use",
    "private": false
  },
  "include_kinds": ["decision", "project_state", "technical_note", "idea"],
  "exclude_statuses": ["archived", "stale", "discarded"],
  "limit": 20
}
```

Response:

```json
{
  "query": "...",
  "context_pack": {
    "current_state": [],
    "hard_constraints": [],
    "prior_decisions": [],
    "background": [],
    "references": [],
    "forbidden_directions": []
  },
  "items": [
    {
      "id": "...",
      "summary": "...",
      "kind": "decision",
      "authority": "user_decision",
      "retrieval_role": "hard_constraint",
      "confidence": 1.0,
      "source": "manual",
      "agent_source": null,
      "score": 0.91,
      "reason": "semantic match + decision role + high importance"
    }
  ]
}
```

Implementation notes:

- Reuse current `recall()` internally.
- Add a second ranking pass that incorporates kind, authority, lifecycle state, importance, recency, recall_count, and private permission.
- Keep the raw memory list available for debugging.

### 4. Candidate Memory Review Flow

Problem:

Agent outputs should not automatically become durable memory. Shared memory needs a staging area.

Target capabilities:

- Store candidate memories before promotion.
- Track source agent and source run.
- Allow accept, edit, merge, reject, or discard.
- Prevent rejected candidates from participating in normal recall.

Suggested schema:

```sql
CREATE TABLE IF NOT EXISTS memory_candidates (
  id TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  summary TEXT,
  proposed_tags TEXT,
  proposed_kind TEXT,
  proposed_authority TEXT,
  proposed_retrieval_role TEXT,
  confidence REAL DEFAULT 0.7,
  source TEXT NOT NULL,
  source_agent TEXT,
  source_run_id TEXT,
  private INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  review_note TEXT,
  created_at TEXT NOT NULL,
  reviewed_at TEXT,
  reviewed_by TEXT,
  promoted_memory_id TEXT
);
```

Candidate statuses:

- `pending`
- `accepted`
- `edited`
- `merged`
- `rejected`
- `discarded`

CLI/API candidates:

- `memoria candidate list`
- `memoria candidate accept <id>`
- `memoria candidate reject <id>`
- `GET /api/candidates`
- `POST /api/candidates`
- `POST /api/candidates/{id}/promote`
- `POST /api/candidates/{id}/reject`

Write policy:

- Manual user writes can still go directly to durable memory.
- On this device, local agents default to trusted durable writes.
- A trusted agent can be allowed direct writes only with a clear source and kind.
- Candidate staging remains for uncertain, external, or delegated outputs that
  still need review.

### 5. Memory Lifecycle Management

Problem:

`active` and `archived` are not enough for shared long-term memory. Memories evolve. Some are superseded, stale, conflicted, pinned, or discarded.

Target capabilities:

- Add explicit lifecycle status.
- Track supersession relationships.
- Keep archived memory separate from discarded memory.
- Allow pinned memory to bypass dormant archiving.

Suggested statuses:

- `candidate`
- `active`
- `pinned`
- `stale`
- `superseded`
- `conflicted`
- `archived`
- `discarded`

Suggested schema:

```sql
ALTER TABLE memories ADD COLUMN status TEXT DEFAULT 'active';
ALTER TABLE memories ADD COLUMN superseded_by TEXT;
ALTER TABLE memories ADD COLUMN valid_from TEXT;
ALTER TABLE memories ADD COLUMN valid_until TEXT;
```

Compatibility:

- Existing `archived=1` should map to `status=archived`.
- Existing active records should map to `status=active`.
- Keep `archived` during transition to avoid breaking old code.

Behavior:

- Normal recall should include `active` and `pinned`.
- Structured recall may include `superseded` only as historical context.
- `conflicted` should appear with warning metadata.
- `discarded` should not appear in normal recall.
- `pinned` should not be archived by dormant maintenance.

### 6. Explainable Recall

Problem:

Agents and users need to know why a memory was recalled. This is essential for trust and correct use.

Target capabilities:

- Return recall reasons.
- Show scoring components.
- Distinguish semantic match, tag match, kind boost, authority boost, importance boost, recency boost, and lifecycle penalties.
- Log recall events for future analysis.

Suggested response fields:

```json
{
  "id": "...",
  "score": 0.91,
  "reason": "semantic match + user decision + hard constraint",
  "score_parts": {
    "semantic": 0.72,
    "tag": 0.1,
    "importance": 0.05,
    "authority": 0.08,
    "recency": 0.02,
    "status_penalty": 0
  }
}
```

Suggested schema:

```sql
CREATE TABLE IF NOT EXISTS recall_events (
  id TEXT PRIMARY KEY,
  query TEXT,
  agent TEXT,
  endpoint TEXT,
  result_ids_json TEXT,
  score_parts_json TEXT,
  created_at TEXT NOT NULL
);
```

Implementation notes:

- Start with reason strings and score parts generated by deterministic ranking logic.
- Do not require LLM explanations for recall.
- Keep recall logs bounded or add cleanup policy.

## Multi-Agent Requirements

Add agent identity as a first-class source field.

Suggested additions:

```sql
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  trust_level TEXT NOT NULL DEFAULT 'trusted_writer',
  can_read_private INTEGER DEFAULT 0,
  can_write_durable INTEGER DEFAULT 1,
  created_at TEXT NOT NULL
);

ALTER TABLE memories ADD COLUMN source_agent TEXT;
ALTER TABLE memories ADD COLUMN source_run_id TEXT;
```

Trust levels:

- `candidate_only`: writes always become candidates.
- `trusted_writer`: can write durable memory with required metadata.
- `read_only`: can recall but not write.
- `private_allowed`: can read private memory if also explicitly requested.

Rules:

- Agent writes must include `source_agent`.
- Agent writes should include `kind`, `authority`, and `retrieval_role`, even if proposed.
- Private memory should never be included for an agent unless request scope and agent permission both allow it.
- Recall should include provenance so downstream agents know where each item came from.

## Suggested Implementation Order

### Phase 1: Metadata Foundation

Scope:

- Add `kind`, `authority`, `retrieval_role`, `confidence`, `status`, `source_agent`, and `source_run_id`.
- Keep compatibility with existing fields.
- Preserve new metadata in Markdown front matter.
- Backfill old DB rows with safe defaults.

Validation:

- Existing recall still works.
- Existing Web UI still loads.
- Existing store/read/rebuild paths preserve data.

### Phase 2: Candidate Review

Scope:

- Add candidate table and CLI/API.
- Route agent writes into candidates by default.
- Promote candidate into normal memory through existing `store()` path.

Validation:

- Candidate creation does not affect recall.
- Accepted candidate becomes durable memory.
- Rejected candidate remains excluded.

### Phase 3: Lifecycle Status

Scope:

- Add lifecycle status handling.
- Map old archived behavior.
- Update dormant maintenance to use status.
- Add superseded relationship.

Validation:

- `pinned` memories are not archived.
- `discarded` memories do not recall.
- `archived` compatibility remains intact.

### Phase 4: Structured Recall

Scope:

- Add `/api/recall/context`.
- Add role grouping and explainable item metadata.
- Add CLI equivalent.

Validation:

- Flat recall behavior remains stable.
- Context recall returns grouped context.
- Private filtering is respected.

### Phase 5: Governance Issues

Scope:

- Add governance issue table.
- Extend maintenance commands.
- Add Web/API review queue later.

Validation:

- Duplicate/conflict/stale detection creates issues without mutating memories.
- Resolving issues is explicit.

### Phase 6: Recall Explainability And Logs

Scope:

- Return reason and score parts.
- Add recall event logging.
- Add bounded cleanup.

Validation:

- Agents receive enough provenance to use recalled memories correctly.
- Recall logs do not grow without limit.

## Files To Inspect First

Start with:

- `memoria/core.py`
- `memoria/db.py`
- `memoria/filestore.py`
- `memoria/maintain.py`
- `server/app.py`
- `cli.py`
- `docs/ARCHITECTURE.md`

Expected edit areas:

- DB schema and migrations in `memoria/db.py`.
- Front matter read/write in `memoria/filestore.py`.
- Store/recall metadata flow in `memoria/core.py`.
- Maintenance governance in `memoria/maintain.py`.
- API endpoints in `server/app.py`.
- CLI commands in `cli.py`.

## Compatibility Requirements

- Existing memory files remain readable.
- Existing DB can migrate in place.
- Rebuild from Markdown remains possible.
- New metadata should be stored in Markdown front matter so DB remains rebuildable.
- Existing `/api/memories`, `/api/search`, `/api/stats`, `/api/labels`, and `/api/graph` should continue to work.
- Web UI should not need major changes in Phase 1.

## Non-Goals For This Work

- Do not build Continuum inside Memoria.
- Do not add full task/workspace orchestration.
- Do not make a large desktop app here.
- Do not require a cloud service.
- Do not make unknown external agent outputs automatically trusted by default.

## Success Definition

Memoria is successful as a shared agent memory substrate when:

- Multiple agents can write with attribution.
- Untrusted writes can be reviewed before becoming durable.
- Memories have explicit semantic type and lifecycle state.
- Recall can return structured context, not only flat search results.
- Users and agents can see why items were recalled.
- Memory quality issues can be surfaced and resolved without corrupting source data.
