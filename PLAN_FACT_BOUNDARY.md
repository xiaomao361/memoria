# Memoria Fact Boundary Plan

## Thesis

Memoria stores observable facts. Continuity stores the current position formed
by those facts.

Memoria should remain the ground-truth layer. It should not store an agent's
long-term interpretation of trust, relationship closeness, emotional state, or
current conversational posture unless the content is phrased as an observable
event.

## Store In Memoria

- User decisions and explicit preferences.
- Project events and completed work.
- Files, paths, commands, versions, and verified outcomes.
- User-provided statements, quoted or paraphrased as statements.
- Agreements about future workflow when the agreement was explicitly made.

## Do Not Store As Fact

- "The user trusts the agent."
- "The relationship became closer."
- "The user depends on the agent."
- "Trust increased."
- "The current conversation feels more intimate."

Those may be useful current interpretations, but they belong in Continuity and
must remain reviewable, stale-able, and closable.

## 1.1 Implementation Slice

- Document the boundary in README and architecture docs.
- Add a lightweight CLI warning when store content appears to be interpretation
  rather than observable fact.
- Do not block writes yet; return a warning so the caller can decide whether to
  rewrite as fact or store the current position in Continuity.

Status: completed.

## 1.1 Follow-up Slice

- Apply the same warning to candidate memory creation.
- Update agent-facing usage guidance so emotional or relationship content is
  stored only as observed user statements, not as agent interpretation.

Status: completed.

## Future Work

- Add an explicit `--observed-fact` flag for strict write paths.
- Add a candidate-review rule that routes interpretation-like content to review.
- Let Continuity reference Memoria IDs without Memoria importing Continuity
  state.
