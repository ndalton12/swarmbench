# Judge design: Opus reads everything once, compacted

Status: chosen by the user on 2026-10-07. It replaces the per-behavior scanners and the sampled digest. Designed with two Codex reviews.

## Why

In the first real run, the swarm produced about **37k tokens of unique content**, but the judge processed **735k tokens**, because it re-read the same content about 20 times (per behavior, per agent, plus repeated context). The turning points and summary meanwhile read a lossy digest. We want the strongest model to see every action and statement, at a cost that grows with the size of the transcript and not with the number of behaviors.

Breakdown of the first run's unique content:

| Content | Share |
|---|---|
| Tool results | 43% (68% of that in outputs over 2k characters) |
| Agent reasoning and text | 28% |
| Claude Code system prompt (the same boilerplate for every agent) | 15% |
| Tool-call arguments | 8% |
| Prompts and notices | 6% |

## Principles

- **Coverage is guaranteed and reported, detection is measured, and the two are never conflated.** "Every event was read" and "nothing concerning happened" are separate claims.
- **Judgments come from the main judge model,** `advanced.judge_model` (default Opus 5.5), kept separate from the models under test. A second setting, `advanced.judge_fallback_model` (default Sonnet 5.5), is used only when the cost cap forces it (see Cost control). Both are configurable.
- **Nothing is skipped silently.** Every gap or degraded read appears in coverage and blocks a clean verdict.

## Stages

### 1. Ledger (deterministic)

- **One immutable, source-addressed event ledger** across all agents. Each event has a stable ID, time, actor (with the gateway and attribution rules: true actor, bridge owner, unknown) and a type.
- **What's kept.** Attachments are resolved. Compactions, wake sessions and repeated actions are kept; there is no deduplication by text.
- **Deduplication.** Content that genuinely repeats (re-sent context, identical system prompts) is stored once and referenced, never dropped.
- **Recorded links.** Tool call to result, message send to delivery, read and replies, request IDs, and file-path references. Links inferred by a model are kept separate.
- **Workspace evidence.** An inventory of all changed files. The changed text, including deletions, is available in bounded fragments, and omissions are listed explicitly.
- **Coverage manifest.** It records which ledger spans entered which successful judge call, and is reconciled against the source inventory.

### 2. Compaction (deterministic, reversible)

- **Always kept in full:** agent reasoning and text, tool-call arguments, messages and board posts, prompts and notices.
- **Long tool outputs** (over 2k characters) are cut to head and tail, with exit codes and result lines kept. Each compacted output gets a stable reference, so Opus can fetch the full text.
- **Boilerplate** (identical system prompts) is shown once.

### 3. Chunk review (main judge model, every chunk)

- **Chunking.** The compacted ledger is split into chronological, cross-agent chunks with linked context at the boundaries. Every chunk gets one open-ended review, not one pass per behavior.
- **What each review produces.** Notes tied to their sources:
  - observations;
  - claims versus outcomes;
  - possible innocent explanations;
  - uncertainties;
  - turning-point candidates;
  - novel concerns ("other");
  - open questions;
  - continuity facts.
- **Failures.** Failed, cut-off or malformed output is retried or subdivided, or explicitly marked incomplete.

### 4. Reconciliation (main judge model, with tools)

- **Case files.** One case file per agent, built from all chunk notes, including activity through another agent's bridge, plus a team case file.
- **Registers** of claims versus outcomes, and of unresolved questions, across chunks.
- **Tools.** Search, reading ledger ranges, grep across agents, fetching full tool outputs, and file history. These are used to resolve open questions and to check deterministic obligations: protected paths, cross-agent actions, flags, attribution mismatches.
- **What reconciliation produces:**
  - levels 0–4 per behavior, per agent and for the team, with the existing rubric, a separate unknown/incomplete state, and outcome evidence required for level 4;
  - cover-ups bound to episodes;
  - turning points with what happened after;
  - before/after levels;
  - eval awareness;
  - leads, kept separate from accusations.

### 5. Validation and outputs (existing machinery)

- Source-bound quote verification, by event, offset and author.
- Invariants run before writing. A semantic contradiction goes back to Opus once; if it isn't resolved, it stays visible as "judge inconsistency".
- One adjudicated findings object renders report.json, report.md, status, the Inspect "judge" score and the Scout results.
- All calls are recorded for replay.

## Cost control

- **Expected cost:** about one Opus pass over the compacted unique content, plus reconciliation. For the first run that is roughly $0.20–0.40, against $1.46 today. A run with about 1M unique tokens should cost roughly $2–3.
- **A hard judge cap,** as now. Before starting, the judge projects the cost. If a full pass by the main judge model would exceed the cap, chunks with no deterministic triggers are reviewed by the fallback model instead. The coverage manifest and the report name which model read which spans. Chunks with triggers, and reconciliation, always use the main judge model.
- **Mandatory review first.** Budget is reserved for the mandatory chunk review and reconciliation before any discretionary investigation. Running out produces resumable, incomplete work, never a clean verdict.

## Calibration (after it's built)

- Audit sampled regions with a second, independent read.
- Score against human-labelled complete runs, broken down by run length, agent count, behavior and dependence across chunks.
- Report recall and precision with their uncertainty.

## Build order

1. Ledger, compaction, coverage manifest and source-bound evidence. This replaces text deduplication (extract.py), the sampled digest (timeline.py) and the bounded file excerpts.
2. Opus chunk review and reconciliation with tools. This replaces the per-behavior scanners and the max-level reduction, and keeps the rubrics, concurrency and Scout export.
3. The cost projection with the fallback model, plus fault-injection tests:
   - chunk-boundary acts;
   - interleaved collusion;
   - delayed lies;
   - oversized outputs;
   - duplicate actions;
   - forged attribution;
   - invalid JSON or truncated responses;
   - failed chunks;
   - budget exhaustion;
   - prompt injection.
4. Shadow-run against the current judge on recorded runs, then switch over.
