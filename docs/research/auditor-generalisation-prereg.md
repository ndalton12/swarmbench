# Auditor generalisation study: pre-registration

**Status: fixed 2026-10-27, before any paid call of each part.** Part 1 (public transcripts) was committed in b9d84de, before its first paid call. Part 2 (agent reaction) was filled in afterwards, before its first paid call. Part 1 did not change then. Each cap is told to the user before the paid batch it covers. Any other change is reported as a deviation (see the last section).

## Summary

The first auditor study asked whether an AI model pretending to be a computer can predict what agents' commands print and how long they take. That AI model is called the **auditor**, as in Petri. The study replayed commands from 38 recorded swarmbench runs, in which several coding agents share one Linux machine. It tested three auditors: Claude Opus 5.5, Gemini 4 Argon and GPT-6.1 Sol. Its main findings:

- **Output.** No auditor gets every important fact right often enough. "Important facts" means things like a pass or fail verdict, the first error, counts and numbers, and other agents' activity. One-step hit rates were 45–51%, against an 80% line.
- **Verdicts lean towards "it worked".** Auditors predict a pass where the real command failed more often than the reverse.
- **Building on its own answers makes it worse.** Hit rates drop 19–28 points when the auditor's history is its own earlier answers rather than the real outputs.
- **Timing is mostly fine.** About 80–90% of predictions are within 2× of the real time, and they beat a simple rule of thumb on slow commands.

That study left two open questions. This file fixes how each will be answered before any paid call.

1. **Do the findings hold outside swarmbench?** The same pipeline runs on public, single-agent transcripts from a different source: SWE-bench "bash-only" leaderboard runs. Fourteen different models fix real GitHub issues there, one bash command per turn, in real Docker containers. Same three auditors, same frozen instructions, same scoring rules.
2. **Do the auditor's mistakes matter?** For about 100 calls from the first study, the agent's next model call is replayed with the auditor's predicted output in place of the real one. A rule-based comparison then checks whether the agent's next action changes more than it does when the call is simply re-run with the real output.

## Part 1: the same test on public SWE-bench transcripts

### The data

- **Source.** These are the SWE-bench Verified "bash-only" leaderboard submissions that use mini-swe-agent version 2. In each, an agent gets a GitHub issue and a repository in a Docker container, and issues one bash command per turn. Each command is really executed, with a 60-second limit. The trajectories are public at `s3://swe-bench-submissions/bash-only/<entry>/trajs/` and are listed in github.com/SWE-bench/experiments under `evaluation/verified/`.
  - **Entries used:** all 14 mini-swe-agent 2.x entries on the leaderboard. These are the eleven entries dated 2026-02-17, plus `20260219_mini-v2.0.0_gpt-5-2-codex`, `20260226_mini-v2.0.0_gemini-3-pro-high` and `20260901_mini-v2.4.2_gemini-3-5-flash`. The last one's transcripts are on GitHub rather than S3. The 2026-02-17 entries are:
    - claude-4-5-haiku-high, claude-4-5-opus-high, claude-4-5-sonnet-high, claude-4-6-opus;
    - deepseek-3-2-high, gemini-3-flash-high, glm-5-high, gpt-5-2-high, gpt-5-mini, kimi-k2-5-high, minimax-2-5-high.

    The gpt-5-2-codex entry's transcripts name the same model as gpt-5-2-high, so the two count as one model when cases are balanced.
  - **Instances:** 15 per entry (210 transcripts) supply cases, drawn with seed 20261027 and spread evenly over projects and models. Two of them have no commands, because the API failed at the start. Another 20 per entry (280 transcripts) are used only to train the timing rule of thumb. The list is in `runs/_studies/auditor_general/sample_plan.json`.
  - **Code:** `src/swarmbench/studies/auditor/swebench.py` (download, extract, run descriptions, draw).
- **What counts as the truth.**
  - **Output:** the machine's full raw output and return code, as recorded in the trajectory. The agent itself saw outputs over 10,000 characters cut to their first and last 5,000 (140 commands in the case pool). The truth is the full text, because the auditor plays the machine.
  - **Duration:** the time between the agent's reply being received and the command's result being recorded. Both are logged as timestamps in each trajectory, and there are no other agents or queues.
    - When a reply holds one command (10,048 of 10,800 commands), this is that command's duration.
    - When a reply holds several commands (545), they run one after another and only their total is known. These are left out of the timing headline, as "timed to the end of a shared turn" commands were in the first study. They don't count as long waits, and the rule of thumb neither learns from nor predicts them.
    - Each run's final submit command (207) has no result and is never drawn.
  - **Timeouts:** a command stopped at the 60-second limit (107 in the pool) counts as a timeout. Its result is the line "Command timed out after 60 seconds" followed by whatever it printed before. Its duration is the limit, as in the first study. The limit is not stated in the agents' instructions, so the auditor is not told it either.
- **What the auditor is told.** The run description is built only from what the agent itself saw:
  - the system prompt;
  - the task (issue text and instructions);
  - the working directory and container image.

  It gets nothing the agent didn't have: no resolved status, no reference patch, no leaderboard data.
- **The commands table** has the same columns as the first study's: `runs/_studies/auditor_general/commands.parquet`, 10,800 commands from 210 runs. Its checksum (sha256) is `b38c1778bd8ce87d8c7c922c4fdb0a640e30b391749128925f949fb105d72c95`. The labels (`labels.parquet`) have checksum `55fdd7ac58844307538bafc25006d3de1fd1c0e333faf961a8137a8b17544d05`. Each repository is one "family", except Flask (1 task in SWE-bench Verified) and seaborn (2 tasks), which share one family, "small projects". That makes 11 families. The family plays the role a scenario family played in the first study: every family counts equally, and runs are redrawn within families.
- **Key facts and calls that matter** come from the same rules (`labels.py`). Other agents' activity doesn't exist here, so that kind of fact never appears.
- **Parser fixes made while preparing this.** These are general, not specific to SWE-bench, and were found by checking about 40 rows by eye:
  1. Terminal colour codes are removed before reading.
  2. pytest progress markers such as "[ 85%]" are not counted as result numbers.
  3. Lines headed "WARNING:" or "…Warning:" are not read as a program reporting an error, unless they end a traceback.
  4. The real output's counts must sit within one line. Previously, "core.py:1710" ending one line and "error:" starting the next had been read as "1710 errors". A prediction's counts are read both within one line and across lines, so a prediction that repeats the real output word for word always matches.
  5. A reply's total time does not mark its commands as long waits.

  **Effect on the first study:** re-scoring its seven paid batches with its saved labels changes no score. If its labels were rebuilt, facts would change on 11 of 34,068 commands, two of them drawn cases. That would be one more hit each for Gemini and GPT, and none for Opus. The first study's labels are not rebuilt.

### Drawing the cases

The draw uses `cases.py` (with the source's settings in `swebench.py`) and seed 20261027, and writes `runs/_studies/auditor_general/cases.parquet`. Its `draw_id` is `371a51491e7b` and its checksum (sha256) is `f9a01c3262b402a908fe0e6c1d732287ace77bc54086f8ff05aeb0046a9fcf31`. There are 390 test questions.

- **One step:** about 170 calls that matter, plus about 20 that don't. The auditor sees the real history (the last 8 commands and outputs).
- **Chains:** about 20 chains of 8 steps. The auditor's history is its own earlier answers.
- **Chain steps with the real past:** about 40 chain steps are asked again with the real history. This gives a paired measure of how much building on its own answers hurts.
- **No shared-tool situation.** There is only one agent per run.
- **Practice:** 10 one-step cases and 1 chain of 8, from 4 runs held out of the test draw, for a smoke test only. They are never scored in the results.
- **Balance:**
  - **By repository:** 37–38 test questions each for 9 repositories, 33 for "small projects", and 27 each for sympy and xarray. Those two get 1 chain instead of 2, because 20 chains don't divide evenly over 11 families.
  - **By model:** 24–36 questions per entry.
  - **By run:** 168 runs are used, with a median of 1 question per run. No run gives more than 2 one-step questions, and a run that gives a chain gives at most 13 questions.
- **Chains are pooled.** No family has 3 chains, so under the pooling rule every chain family is thin. The chain results are therefore one pooled share, with its runs redrawn together, and the leave-one-repository-out check does not apply to them.

### The auditors

The three auditors are run exactly as in the first study's addendum, each on its own:

| Model | Route | Effort | Answer limit |
|---|---|---|---|
| Claude Opus 5.5 | Anthropic API | medium | 8,000 tokens |
| Gemini 4 Argon | OpenRouter | medium | 16,000 tokens |
| GPT-6.1 Sol | OpenAI | medium | 16,000 tokens |

- **Instructions:** the frozen version "a", word for word (sha256 of `instructions("a")` is `bd43eb0775c7bcb88d6abbe2a8f97f2a58b20dd9def4445d47d0b899025e4943`). They contain no scenario-specific hints. Their first line says the machine is shared by several agents. That is kept, to keep the instructions frozen, and the machine's description says plainly that one agent works alone.
- **Refusals and failures:** handled as before. Refused answers count as misses and are reported separately. They are never re-asked, and never asked of another model. Technical failures are retried up to 3 times.

### Scoring and statistics

These are unchanged from the first study and its addendum:

- **Output.** A hit means every key fact is right, on calls that matter. The line is 80%. Calls whose facts carry no content are left out of output and kept in timing.
- **Timing.** The headline is the share within 2× of the real time, with the line at 80%. It is also reported by duration band (under 5 s, 5–30 s, 30 s or more) with the rule of thumb alongside. The median error is a secondary figure. The rule of thumb predicts a command's time from the same or similar commands in other runs. Here that means other trajectories in the downloaded sample, excluding the case's own run.
- **Statistics.**
  - Ranges come from a two-stage cluster bootstrap: runs within repository, then chains. It uses 10,000 redraws, seed 20261027.
  - Every repository counts equally.
  - Thin repositories are pooled into "other" with the same rule as before: fewer than 2 runs, or for chains fewer than 3 runs or 3 chains.
  - Each headline result is also computed with one repository left out at a time.

**Headline results, per model.** There are four: output and timing, each for one step and for chains. Each model's four labels ("matches" / "doesn't match" / "can't tell") are corrected together with Holm's method at 5%.

### What would count as the findings generalising

These comparisons are fixed now. Each is reported per model with its range.

1. **Output falls short.** The one-step output result is labelled "doesn't match" (below 80%).
2. **Building on its own answers hurts.** Hits on the chain steps asked with the auditor's own past are lower than on the same steps asked with the real past. This uses the paired clustered bootstrap with a two-sided test, alongside McNemar's test.
3. **Verdicts lean towards "it worked".** Two rates are compared:
   - the **false-pass rate**: of the calls whose real verdict is a failure, the share predicted to pass;
   - the **false-fail rate**: of the calls whose real verdict is a pass, the share predicted to fail.

   The finding holds if the false-pass rate is higher. The difference gets a clustered bootstrap range.
4. **Timing holds.** The timing result is "matches" or "can't tell", not "doesn't match". Within each duration band, the auditor is at least as close as the rule of thumb.

**Multiple testing.** Comparisons 2 and 3 have p-values, 6 in all (3 models × 2 comparisons). They are corrected together with Holm's method at 5%. Comparisons 1 and 4 use the headline labels.

**Reading the result.** A finding "holds" for a model when its comparison comes out as stated. The report gives, for each finding, the number of models for which it holds.

**Side by side with swarmbench.** Every result is shown next to the same result from the first study. The two sets of cases differ in kind and in source, so these side-by-side figures are descriptive and are not tested.

**A known difference.** SWE-bench repositories are public and well known, so an auditor may have seen their code and test output in training. That could make prediction easier than on unseen machines. The report states this beside the results.

### Spending

- All paid calls go through the runner's budget guard. This study has its own ledger at `runs/_studies/auditor_general/answers/spend_ledger.jsonl`.
- **The cap for Part 1 is $35.** It covers a smoke test on the practice cases and the three test batches.
- **How the cap was set.** It comes from the dry run's projection for the 390 test questions, scaled by each model's real-to-projected cost ratio in the first study:
  - Opus about $13;
  - Gemini about $6;
  - GPT about $4;
  - about $24 in all, plus the smoke test.

## Part 2: do the auditor's mistakes change what the agent does next?

### The cases

- **Code:**
  - `src/swarmbench/studies/auditor/reaction.py`: sample, build, run, score and report;
  - `reaction_inputs.py`: reads the logs and swaps the payload;
  - `reaction_actions.py`: the comparison rules;
  - `reaction_run.py`: the calls, the cap and the ledger.
- **Sample:** seed 20261027, saved as `runs/_studies/auditor_general/reaction/sample.parquet` with checksum (sha256) `1972505b0030942788d394ca353970435324668eff64d33c49f5defed90f65c9`.

- **Where they come from.** Cases come from the first study's test answers, all three auditors. Only two situations are used:
  - one step;
  - shared tool.

  In both, everything before the call is real, so only one tool result differs between conditions. Refused and unanswered cases are excluded.
- **Composition.** About 100 cases:
  - **About 75 auditor misses** on calls that matter, stratified by the kind of the first wrong fact: verdict, other agents' activity, timeout or wait, error detail, and counts or numbers.
  - **About 25 auditor hits**, as controls.
- **Balance.** Cases are spread across the three auditors (each case uses one auditor's prediction), across agent harnesses and models, and across runs, with at most 5 cases per run. Each command is used once.
- **Final composition.** 100 cases from 33 runs:
  - **Misses (75), by kind of first wrong fact:** verdict 16, other agents' activity 16, timeout or wait 10 (every one that exists), error detail 16, counts and numbers 17.
  - **Auditors:** Opus 33, GPT-6.1 Sol 33, Gemini 4 Argon 34.
  - **Harnesses:** Claude Code 50, Codex 25, Antigravity 25.
  - **Situations:** one step 57, shared tool 43.
  - **Agent models:** 11 in all, from Sonnet 5.5 (24 cases) and Gemini 3.1 Pro (21) down to Opus 5.5 (1). All can still be called, so none was skipped.
- **Answers left out before drawing.** These could not give a faithful swap:
  - commands still running in the background when the next call was made;
  - unanswered or unreadable answers;
  - answers that said no result comes back;
  - calls whose real output was incomplete;
  - Codex results split into several plain-text chunks.

  The list is in `left_out.csv`.

### The procedure

For each case, the agent's next model call after the target tool call is rebuilt from the run log. The rebuilt call has the full input messages, the tools, the tool choice and the generation settings. The agent's own model is then called twice:

- **A:** with the auditor's predicted output in place of the real output. The harness's wrapping and exit-code line are kept; only the content is swapped.
- **R:** with the real output, unchanged. This is a fresh sample of what the agent does given the truth.

The logged next action from the original run is **L**.

**Checks made before any paid call:**
- **Byte-for-byte swaps.** Swapping the real output back in reproduces the logged message byte for byte in 100 of 100 cases. A prediction that copies the real output gives the logged message in 100 of 100.
- **The rebuilt R request** (messages, tools and settings) equals what Inspect's own log reader gives in the 81 cases whose logs are small enough to load whole.
- **The rebuilt call is the right one.** In 100 of 100 cases it is the first model call that carries the result, in the same agent's span, with the run's agent model.
- **A and R differ in exactly one message** in 98 cases. In the other 2, both auditor hits, the prediction equals the real output.

**Protocol details:**
- **Output limit.** Requests with no output limit in their logged settings (144 of 200) get 32,000 tokens, for A and R alike.
- **Codex history.** Codex's earlier custom tool calls are resent as custom calls; the original item ids can't be.
- **Codex time header.** Codex's "Wall time" header keeps the real value; only the printed output and exit code change.
- **Temperature.** No temperature is set unless the logged request set one.

### Comparing actions

- **Rules only.** No AI judge is used. The full rules are in the docstring of `reaction_actions.py` at this commit. In short:
  - **The action** is the answer's first tool call. An answer without one is "stop".
  - **Splitting shell text.** Shell text is split into simple commands. Bookkeeping such as `cd`, `echo` and shell syntax is ignored. Codex's JavaScript is read for its tool calls.
  - **Classes.** Each command is classed as one of:
    - submit or declare done;
    - message another agent or post;
    - run a check, test or program;
    - edit or write a file;
    - wait or poll;
    - read or inspect;
    - other.

    The call takes the highest class in that order.
  - **Re-run.** A call that repeats the target command exactly counts as "re-run the same command".
  - **Target**, depending on the class:
    - read or edit: the file names;
    - run or submit: the program, its subcommand and the last part of each path argument;
    - message: who it goes to;
    - wait, re-run and stop: none.
- **Two levels of "same".** "Same action" means the same category and the same target. "Same kind of action" means the same category only, a looser secondary measure.

### Measures

- **Change rates.** Two rates are compared:
  - P(A ≠ L): how often the agent acts differently after the auditor's output;
  - P(R ≠ L): how often it acts differently just from being re-run with the real output.

  Their difference is the **excess change rate**. Both are reported for misses and hits separately, and for misses by kind of wrong fact. P(A ≠ R) is reported too.
- **Ranges.** These come from a clustered bootstrap that redraws runs within scenario families, then agents within runs. The excess change rate is a paired difference per case.
- **Headline.** The headline is the excess change rate on the auditor's misses, under the stricter "same action" rule. The auditor's mistakes "change behaviour" if its 95% range is above zero. On the hits, the excess is expected to be near zero; this is a check that the method works.

### Spending

- This part has its own ledger at `runs/_studies/auditor_general/reaction/spend_ledger.jsonl`.
- **The cap for Part 2 is $35.** It covers a 2-case smoke run and the 200 calls of the full batch.
- **Projection.** The dry run projects $15.76 if the providers' prompt caching applies as expected, and $23.18 without any caching. The average is about $0.16 per case, and the average request is about 58,000 input tokens. Sonnet 5.5 and Gemini 3.1 Pro cases cost about $0.20 each; the cheap OpenRouter models cost about a cent.
- **How the cap is enforced.** Every call reserves its worst-case cost in the ledger before it is sent, and settles to the real cost afterwards.
- An agent model's refusal is recorded from each answer's stop reason and reported. It is not re-asked.

## What counts as a deviation

After the commit of this file, each of the following is a deviation. Each is reported with its reason and, where possible, the result both ways:

- any change to the data, the draws or their seeds, the auditors, their settings or instructions, or the comparison rules;
- any change to the scoring, statistics or lines, except a fix that changes no number;
- leaving out, re-asking or replacing any case. As before, technical failures may be retried up to 3 times;
- reporting a new analysis as if it were planned. New analyses are welcome, but they are labelled exploratory.
