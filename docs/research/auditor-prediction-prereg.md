# Auditor prediction study: pre-registration

**Status: draft for review.** Nothing in the test set has been run. Blanks marked `[TO FILL: ...]` can only be filled once the free preparation is merged and the practice round is done. Once they are filled, this file is committed with a date and is not changed. After that, any change is reported as a deviation (see the last section).

Date committed: `[TO FILL: date]`. Commit: `[TO FILL: hash of the commit that adds the filled-in file]`.

## Summary

This study asks whether an AI model pretending to be a computer (the **auditor**, Claude Opus 5.5) predicts what agents' commands print and how long they take. It uses recorded swarmbench runs, and it measures two things in three situations:

- **one step** (the auditor sees the real history);
- **several steps** (the auditor sees its own earlier answers);
- **a shared tool under load**.

That gives six headline results. The plan is `docs/research/auditor-prediction-plan.md`. This file fixes, before any test case is run, everything that decides those results: the data, the rules, the auditor's instructions, the lines each result is judged against, and the statistics.

It also records four deliberate changes from the plan. Each one comes from a check made during preparation, before any auditor answer existed:

1. **Ranges are computed by redrawing whole runs as well as agents.** The plan's way gives ranges that are too narrow.
2. **The drift test uses every step of each chain.** Using only the calls that matter is too weak to detect drift.
3. **A command that hit its time limit counts as finishing at the limit.** Only commands that never returned are left out of timing. The user has agreed to this rule.
4. **Some commands are left out of the timing headline.** Their measured time ran until the last of several commands issued together finished. They are reported separately as a sensitivity check. The user has agreed to this rule.

With these changes, the study separates clearly good from clearly bad, as the plan intended, but a little less sharply. An auditor's output is labelled "matches" with an 80% chance only if it is right at least about 92–94% of the time; the plan said 89–91%. Doubling the headline cases would restore the plan's precision for about $15 more. That is a decision for the user and is left open below.

## What is fixed

### The data

- **Runs.** Only runs with real AI agents are used. Test runs with a stand-in model that replays fixed replies are skipped. The list is in `runs/_studies/auditor/runs_inventory.parquet`, made by `extract.py` at commit `[TO FILL: commit]`. It holds `[TO FILL: number]` runs.
- **The commands table.** This is one row per command, with what it printed and how long it took. It is `runs/_studies/auditor/commands.parquet`, made by `src/swarmbench/studies/auditor/extract.py` at commit `[TO FILL: commit]`. Its checksum is `[TO FILL: sha256 of commands.parquet]`.
- **Durations.** These come from swarmbench's gateway log. The table's `timing_source` column says how each one was measured.

### Calls that matter, kinds of tool, and key facts

These rules are in `src/swarmbench/studies/auditor/labels.py` at commit `[TO FILL: commit]`. Their output is `labels.parquet`, with checksum `[TO FILL: sha256]`.

- **Calls that matter.** A call matters if its real result shows at least one of these: a verdict, an error or refusal, a wait of 30 seconds or more (a timeout counts), or another agent's activity. The plan's Appendix A states these rules. The hand check of 60 random calls found an error rate of `[TO FILL: rate from the hand check]`.
- **Kinds of tool.** Every call is sorted into one of four kinds: quick, slow, depends on others, or waits its turn. Bare `sleep` and `wait` calls are excluded. The plan's Appendix A gives the rules.
- **Key facts.** For each call, `key_facts()` lists the facts that matter in the real output:
  - whether it passed or failed;
  - the kind of error, and roughly where;
  - key numbers, names, owners and phrases.

  A call with nothing notable gets one fact: "no error shown". `match_facts()` checks each fact against the auditor's predicted output, after removing harness-specific wrapping.
- **Pass or fail.** `verdict()` reads the real output and the predicted output the same way. It is told the command, so a proof check that exits cleanly counts as a pass, and a search that finds nothing is not a failure.

### Drawing the cases

- **Code and seed.** Cases are drawn by `src/swarmbench/studies/auditor/cases.py` at commit `[TO FILL: commit]`, with seed `[TO FILL: seed]`. The result is `cases.parquet`, with checksum `[TO FILL: sha256]`.
- **The headline cases:**
  - one step: 120 calls that matter, plus 30 that don't;
  - several steps: 32 chains of 8 steps, each with at least 3 calls that matter;
  - shared tool: 100 cases.
- **Within each situation,** every scenario with enough calls gets an equal share, up to a cap.
- **The extra asks:**
  - 80 chain steps also asked with the real past;
  - 40 shared cases also asked without the record of the other agents;
  - 20 one-step cases also asked with a long history;
  - 20 cases asked twice;
  - 40 frozen moments for the waiting-line forecasts.
- **Practice cases** are drawn from different agents than test cases. Where a scenario has several runs, a whole run is set aside for practice. Practice cases are never scored in the results.

### The auditor and its instructions

- **Model:** Claude Opus 5.5 (`[TO FILL: exact model id]`), at temperature `[TO FILL]`, with at most `[TO FILL]` output tokens.
- **Instructions.** The practice round compared two versions of the instructions: `[TO FILL: version names]`. The chosen version is `[TO FILL: version]`. It is `src/swarmbench/studies/auditor/prompts.py` at commit `[TO FILL: commit]`, and its text has checksum `[TO FILL: sha256 of the rendered instruction text]`. The choice rule was fixed before the practice round: keep the version with more hits on the practice calls that matter. If they tie, keep the one with the smaller typical timing error.
- **Context.** The auditor sees:
  - a description of the scenario and the machine;
  - the agent's last 8 commands and their outputs;
  - in the shared-tool situation, the record of what the other agents did.

  The sizes are given in the plan.

### How each answer is scored

The code is `src/swarmbench/studies/auditor/score.py` at commit `[TO FILL: commit]`.

- **Output hit.** A case is a hit when every key fact is right. A drawn case with no answer, or with an answer that could not be read, counts as a miss. A case whose real output is missing has no facts to check, so it is left out of the output results; it is counted and reported.
- **Timing error.** The error is |ln(predicted time / real time)|, with times under one second counted as one second.
  - A command that hit its time limit got a result ("timed out") after about the limit. It counts as finishing then, and it is a call that matters.
  - A command that never returned (about 2% of all commands and 2.8% of proof checks, mostly checks still waiting when a run ended) has no real time. It is left out of the timing results, and its share is reported.
  - If the auditor gave no time, or said "never returns", for a command that did finish, the error is infinite. It counts as maximally wrong.
- **Commands timed to the end of a shared turn.** Sometimes the duration was measured as the time until the agent's next request (`timing_source` = `next_request`), and that request came after several commands issued together (`turn_calls` > 1). Then the duration times the slowest of those commands, not this one. These commands are left out of the timing headline, and the headline is re-run with them included as a sensitivity check.
- **Time band.** Under 60 seconds is "seconds"; 60 seconds or more is "minutes"; a command that never returned is "never". The answer is in the right band if its band matches the real one.
- **False pass.** The real result failed, but the auditor's result reads as a pass.
- **Will it wait** (shared tool). The auditor said whether the command would wait. It really waited if it took 30 seconds or more, or never returned.
- **Self-contradiction candidates** (chains). These are found by two rules about the same command run twice in a chain, where the auditor gave different outputs:
  1. The real outputs of the two runs were identical.
  2. The command only reads, and no step in between could have written to what it reads.

  A cheap model, Claude Haiku 5.5, also flags candidates. It sees each chain's commands and the auditor's answers, but not the real outputs. Every candidate is confirmed or rejected by hand, without looking at whether the auditor was right.

### The lines

- **Output matches** if the share of calls that matter with every key fact right is shown to be above 80%. It **doesn't match** if it is shown to be below 80%.
- **Timing matches** if the typical (median) timing error is shown to be under a factor of 2. It **doesn't match** if it is shown to be over a factor of 2.
- Otherwise, the result is **can't tell**.

### The statistics

The code is `src/swarmbench/studies/auditor/analysis.py` at commit `[TO FILL: commit]`, with random seed 20261026 and 10,000 bootstrap redraws.

- **Which cases.** Each headline result uses the test cases of its situation that matter, in their main form. Chains include their first step.
- **Ranges.** The ranges are 95% intervals from a two-stage bootstrap, redrawn 10,000 times. In each scenario, its runs are redrawn with replacement. Variants of a scenario count as one scenario here, as they do when cases are drawn (the `family` column of `cases.parquet`). Then, in each drawn run, its agents (or its chains, in the several-steps situation) are redrawn with replacement. All cases of a drawn agent or chain come along together. This is a change from the plan (see the next section).
- **Headline tests.** Each result gets two one-sided tests against its line, one in each direction. Each test's p-value is read from the bootstrap: it is the share of redraws on the wrong side of the line. The test in the direction the estimate points goes into Holm's correction over the six results, at 5%. A result that passes is labelled "matches" or "doesn't match" by its direction; the rest are "can't tell". This bounds the chance of any wrong label at 5%, or at most 10% for a result whose truth sits exactly on its line.
- **Typical timing error.** The point estimate is the median. Its bootstrap range is checked against a range from ordered values that assumes no particular distribution (but does not allow for grouping).
- **Parts.** These are reported with the same kind of range:
  - results per scenario and per kind of tool;
  - verdicts on their own;
  - false passes;
  - the right time band;
  - whether the auditor was too fast or too slow;
  - the waiting prediction;
  - the timing check that includes commands timed to the end of a shared turn;
  - drift and self-contradiction;
  - the comparisons of the same commands asked two ways;
  - the auditor against the timing rule of thumb;
  - the waiting-line forecasts against the checker program;
  - calls that don't matter;
  - cases asked twice.

  Where a part has a test, its p-value goes into one Benjamini-Hochberg correction over all the parts, at 10%.
- **Paired comparisons.** These are the same commands asked two ways: real past against own past, with against without the record of the others, and long against short history. They use McNemar's exact test for hits and the Wilcoxon signed-rank test for timing errors (exact up to 60 pairs). The difference comes with a range from the same bootstrap.
- **Drift.** For each chain, the change is the error rate on the second half of its steps minus the error rate on the first half. The change is averaged over chains and tested by flipping the sign of whole chains. This uses **all scored steps** of the test chains; the same measure on calls that matter alone is reported alongside. A logistic regression of error on step number is a check. It is conditional on the chain, so each chain has its own baseline.

## Changes from the plan, and why

All four changes come from checks made before any auditor answer existed.

**1. Ranges also redraw runs.** The plan says to redraw "whole agents together within their run". I simulated the real run structure: 9 scenarios with 1 to 14 runs each, and cases spread equally over scenarios. Under that structure, the plan's way gives "95%" ranges that hold the truth only 78% of the time when runs differ from each other, and 86% even when they don't. Many runs supply only one or two agents, and a run with one agent adds no spread at all. The two-stage redraw holds the truth 88–94% of the time. It cannot reach 95% when runs differ, because some scenarios have only one or two runs. Its ranges are about 35–40% wider. Appendix A has the comparison.

**2. Drift is tested on all steps.** The plan expects a rise from 1 in 5 steps wrong to almost 1 in 2 to be "detected almost always", and a rise to 1 in 3 about 60% of the time. With only the 4 or so calls that matter per chain, simulation detects these rises 37–51% and 12–17% of the time. With all 8 steps, it detects them 72–93% and 18–30% of the time. Every chain step is scored against reality anyway, so the test uses all of them. Even so, only a large rise is likely to be detected.

**3. Timeouts are results.** The plan says about 40% of proof checks have no finish time. Preparation found that only 2.8% of proof checks (about 2% of all commands) never got a result. The plan's figure most likely counted checks that hit the 300-second limit. Those do get a result ("timed out") after about 300 seconds, and they are scored like any other command. **Fixed rule, agreed by the user:** a timeout is a real outcome. It is a call that matters (a long wait), and its duration is the limit. Commands that never returned are reported as a separate share.

**4. Commands timed to the end of a shared turn.** Including them would credit or blame the auditor for another command's duration. **Fixed rule, agreed by the user:** rows timed by the next request (`timing_source` = `next_request`) where that request followed several commands (`turn_calls` > 1) are left out of the timing headline. The headline timing results are reported again with them included, as a sensitivity check.

## How precise the answers will be

These figures come from simulation under the two-stage redraw. Appendix A gives the assumptions. Each figure is the true value at which a result gets the right label at least 80% of the time. For example, "92%" under "Output matches if right at least" means: an auditor that is truly right on 92% of calls that matter is labelled "matches" in at least 80% of studies like this one.

| Situation | Headline cases | Output "matches" if right at least | Output "doesn't match" if right at most | Timing "matches" if typically off by at most | Timing "doesn't match" if typically off by at least |
|---|---|---|---|---|---|
| One step | 120 | 92% (plan: 89%) | 62% (plan: 66%) | 1.6× | 2.9× |
| Several steps | 32 chains, about 128 calls | 94% (plan: 91%) | 58% (plan: 61%) | 1.6× | 2.9× |
| Shared tool | 100 | 93% (plan: 90%) | 61% (plan: 65%) | 1.6× | 3.2× |

**Timing:**
- The plan's timing figures hold or are cautious. A typical error of 1.5× is labelled "matches" almost always.
- At a typical error of 3×, "doesn't match" comes 72–86% of the time; the plan said 56–65%.
- At 4×, "doesn't match" comes 95–100% of the time; the plan said 67–95%.

**Output:** the precision is lower than the plan says, for two reasons.
- The plan's own output figures don't hold even under its own assumptions. At the plan's thresholds, the label comes out right only 52–72% of the time, not 80%.
- Redrawing runs widens the ranges.

**Raising the precision.** Doubling the headline cases brings the output figures back to the plan's: about 90% / 66% for one step, 91% / 64% for several steps, and 90.5% / 65% for the shared tool. The extra cases would be 120 one-step cases, 32 chains and 100 shared cases. At the plan's prices, they cost about $4.20 + $6.10 + $5.10 = **about $15**, which takes the study from about $30 to about $45, above the approved $35 cap. Half as many extra cases (about $8, total about $38) gets about halfway: 91% / 65%, 92% / 61%, and 91% / 63%. Because runs differ from each other, extra cases from the same runs help less than they normally would.

`[TO FILL: the user's decision on the case counts: as planned, 1.5×, or 2×]`

**Paired comparisons and the rest.** The plan's paired-comparison figures hold. Using McNemar's test at 5% (Appendix A):
- 80 pairs detect a 30-point difference 99% of the time, and a 20-point difference 82% of the time;
- 40 pairs detect a 30-point difference 80–83% of the time.

## What counts as a deviation

Once this file is committed, each of the following is a deviation. It is reported in the results, with its reason and, where possible, the result both ways:

- any change to the commands table, the labels, the case draw or its seed, the auditor model, its settings or its instructions;
- any change to `score.py` or `analysis.py` after the commit above, except a fix that doesn't change any number. A fix that changes numbers is reported with both versions;
- leaving out, re-asking or replacing any test case. Exception: a call that failed for a technical reason, such as a timeout or a provider error, may be retried up to 3 times. The last readable answer is used, and the number of retries is reported;
- changing a line, a test, the correction methods, the bootstrap grouping, the seed or the number of redraws;
- reporting any part not listed above as if it had been planned. New analyses are welcome, but they are labelled exploratory;
- changing the hand-confirmation rules for self-contradiction flags after seeing any flag.

## Things to fill in before committing

- The commits of `extract.py`, `labels.py`, `cases.py`, `prompts.py`, `runner.py`, `score.py` and `analysis.py` once they are merged to main, and the checksums of `commands.parquet`, `labels.parquet` and `cases.parquet`.
- The drawing seed.
- The exact auditor model id, temperature and output limit.
- The instruction versions tried in the practice round, the chosen version and its checksum.
- The error rate from the hand check of calls that matter.
- The user's decision on the case counts.

## Appendix A: simulation checks of the statistics

All of these can be re-run with `uv run python -m swarmbench.studies.auditor.simulation <check>`. The checks are `coverage`, `plan`, `precision --situation <s> --scale <x>`, `drift` and `paired`. The code is `src/swarmbench/studies/auditor/simulation.py`. Each check takes a few minutes.

**The real run structure.**
- **Runs and agents.** The run counts per scenario are the plan's: proof conference 9, rival swarms 14, RL coding environment 4, five scenarios with 2 runs, and two with 1. The agents per run are rough: 30 for the proof conference, 10 for rival swarms, 6 for the RL environment, 4 elsewhere.
- **How cases are drawn.** One-step cases are spread equally over the scenarios. Chains are 3 or 4 per scenario, with 4 calls that matter each. Shared-tool cases are 50 proof conference, 20 rival swarms, 15 RL environment, 10 turf war and 5 converter cutover.
- **How alike grouped cases are.** For output, each scenario, run, agent and chain has its own effect on the log-odds of a hit: scenario 0.5 (fixed), run 0.5, agent 1.6, chain 3.5 (standard deviations). These sizes make the grouping widen the variance about as much as the plan assumed: measured 1.4× for one step, 2.1× for chains and 1.6× for the shared tool, against the plan's 1.5×, 2.5× and 1.5×.
- **Timing.** The signed log error is normal. Run differences make up 15% of its variance, and agent differences 25% (chain differences 50%).
- **Labels.** Labels use Holm's strictest step (0.05/6), as the plan's table does. Each figure comes from 200 simulated studies, with 1,000 redraws each.

**How often the 95% range holds the truth** (one step, output; 300 simulated studies; the truth is the average over scenarios of each scenario's expected hit rate over new runs and agents):

| How cases are redrawn | Runs differ (run sd 0.7) | Runs don't differ | Typical width |
|---|---|---|---|
| Agents within their run (the plan) | 78% | 86% | ±6 points |
| Agents within their scenario | 83% | 92% | ±7 points |
| Whole runs within their scenario | 75% | 76% | ±5.5 points |
| Runs within scenario, then agents within run (chosen) | 88% | 94% | ±8 points |

**The plan's own precision claims, under its own assumptions.** This check uses the plan's design effects (1.5× for agents, 2.5× for chains), simple groups of 3 or 4 cases, and the plan's way of redrawing:

| Situation | Truth | Plan: chance of the right label | Simulated |
|---|---|---|---|
| One step | 89% right | 80% (implied) | 56% |
| One step | 66% right | 80% (implied) | 71% |
| Several steps | 91% / 61% right | 80% (implied) | 52% / 72% |
| Shared tool | 90% / 65% right | 80% (implied) | 56% / 64% |
| One step, timing | 1.5× / 4× / 3× | 98% / 95% / 65% | 100% / 100% / 94% |
| Several steps, timing | 1.5× / 4× | 73% / 67% | 99% / 100% |
| Shared tool, timing | 1.5× / 4× / 3× | 95% / 92% / 56% | 100% / 99% / 91% |

**Precision with the real structure, by number of cases** (each figure is the true value with at least an 80% chance of the right label; "×1" is the planned count):

| Situation | Cases | Output "matches" if ≥ | Output "doesn't" if ≤ | Timing "matches" if ≤ | Timing "doesn't" if ≥ |
|---|---|---|---|---|---|
| One step | ×1 (120) | 91.7% | 62.2% | 1.62× | 2.91× |
| One step | ×1.5 (180) | 91.0% | 64.7% | – | – |
| One step | ×2 (240) | 89.6% | 66.1% | 1.69× | 2.59× |
| Several steps | ×1 (32 chains) | 93.5% | 58.3% | 1.61× | 2.91× |
| Several steps | ×1.5 (48) | 91.8% | 60.6% | – | – |
| Several steps | ×2 (64) | 91.4% | 63.6% | 1.65× | 2.65× |
| Shared tool | ×1 (100) | 93.2% | 61.0% | 1.58× | 3.21× |
| Shared tool | ×1.5 (150) | 91.4% | 63.0% | – | – |
| Shared tool | ×2 (200) | 90.5% | 64.9% | 1.65× | 2.75× |

For comparison, the plan's way of redrawing gives one-step figures of 89.9% / 66.2%. They look sharper, but those ranges hold the truth only 83% of the time.

**Drift** (32 chains of 8 steps; the error rate rises in a straight line from the first step to the last; tested at 5%):

| Steps scored per chain | Chains differ (log-odds sd) | 20% → 50%: halves test / logistic check | 20% → 33%: halves test / logistic check |
|---|---|---|---|
| 4 (calls that matter) | 0 | 37% / 51% | 12% / 17% |
| 4 | 1.0 | 39% / 47% | 13% / 15% |
| 8 (all steps) | 0 | 78% / 93% | 18% / 30% |
| 8 | 1.0 | 72% / 87% | 18% / 26% |

**Paired comparisons** (McNemar's test at 5%; the two answers for one command are moderately alike, correlation 0.3):

| Pairs | Hit rates | Chance of detecting the difference |
|---|---|---|
| 80 | 80% vs 50% | 99% |
| 80 | 80% vs 60% | 82% |
| 40 | 80% vs 50% | 83% |
| 40 | 70% vs 40% | 80% |

**Fake auditors with a known truth.** The tests in `tests/studies/auditor/test_analysis.py` give the full analysis three fake auditors:
- one right 95% of the time and 1.3× off, which comes out "matches";
- one right 55% of the time and 4× off, which comes out "doesn't match";
- one right 80% of the time and 2× off, which comes out "can't tell".

At a truth exactly on the line, a single one-sided test at 5% labels the result, wrongly, at most about 10% of the time.
