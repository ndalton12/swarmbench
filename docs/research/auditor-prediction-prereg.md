# Auditor prediction study: pre-registration

**Status: rules fixed 2026-10-26, before the practice round.** Nothing in the test set has been run. This file, with all its rules, is committed **before the practice round** (the first paid step). After the practice round, only three things are filled in: the chosen instruction version, its checksum, and the main batch's spending cap. Those blanks, and the date and commit of this file (filled when it is committed), are marked `[TO FILL: ...]`. Any other change after the commit is reported as a deviation (see "What counts as a deviation").

Date committed: 2026-10-26, before the practice round. Commit: the one titled "Auditor pre-registration: rules fixed before the practice round" (its hash is recorded when the post-practice blanks are filled). The three data checksums and the `draw_id` below were re-checked at this commit and are unchanged.

## Summary

This study asks whether an AI model pretending to be a computer (the **auditor**, Claude Opus 5.5) predicts what agents' commands print and how long they take. It uses recorded swarmbench runs, and it measures two things in three situations:

- **one step** (the auditor sees the real history);
- **several steps** (the auditor sees its own earlier answers);
- **a shared tool under load**.

That gives six headline results. The study is about how well an auditor simulates tools **in general**, across scenarios, not about any one scenario. So every scenario family counts equally in each headline result, and each result is checked again with one family left out at a time. The plan is `docs/research/auditor-prediction-plan.md`. This file fixes, before any test case is run, everything that decides those results: the data, the rules, the auditor's instructions, the lines each result is judged against, and the statistics.

It also records eight changes from the plan. Each comes from a check made during preparation or a decision by the user, before any auditor answer existed, and the user has approved them:

1. **Ranges are computed by redrawing whole runs as well as agents.** The plan's way gives ranges that are too narrow.
2. **The drift test uses every step of each chain.** Using only the calls that matter is too weak to detect drift.
3. **A command that hit its time limit counts as finishing at the limit.** Only commands that never returned are left out of timing.
4. **Some commands are left out of the timing headline.** Their measured time ran until the last of several commands issued together finished. They are reported separately as a sensitivity check.
5. **The headline cases are doubled:** 240 one-step calls that matter, 64 chains and 200 shared-tool cases. The spending cap rises from $35 to $45.
6. **The shared-tool cases are split** half from waiting-line tools (the proof checker and the RL environment's grader) and half from the other shared things.
7. **Every scenario family counts equally** in each headline result. The figure with every case counting equally is shown beside it.
8. **Each headline result is re-checked with one scenario family left out**, and the report says plainly if a label changes.

One planned step was not completed: the hand check of the "calls that matter" rule on 60 random calls. It is recorded as a deviation below.

With these changes, the study separates clearly good from clearly bad. Simulated on the actual drawn cases, an auditor's output is labelled "matches" with at least an 80% chance if it is right at least about 90–93% of the time, and "doesn't match" if it is right at most about 58–66%. The 95% ranges hold the truth about 95% of the time or more in all three situations.

## What is fixed

**Code version.** All the study's code is `src/swarmbench/studies/auditor/` at the commit that adds the filled-in version of this file (top of the file). That one commit fixes every rule below: the extraction, the labels and key facts, the case draw, the instructions, the runner, the scoring, the flags and the statistics.

### The data

- **Runs.** Only runs with real AI agents are used. Test runs with a stand-in model that replays fixed replies are skipped. The list is in `runs/_studies/auditor/runs_inventory.parquet`, made by `extract.py`. It holds 38 runs with real agents (30 test runs are skipped).
- **The commands table.** This is one row per command, with what it printed and how long it took. It is `runs/_studies/auditor/commands.parquet`, made by `src/swarmbench/studies/auditor/extract.py`. Its checksum (sha256) is `8c9abb884191730555c2c05d02dc6227f69a69480c34c91ae1d094b165215c2b`.
- **Durations.** These come from swarmbench's gateway log. The table's `timing_source` column says how each one was measured.

### Calls that matter, kinds of tool, and key facts

These rules are in `src/swarmbench/studies/auditor/labels.py`. Their output is `labels.parquet`, with checksum (sha256) `e4a95ce6c1f8b694faf9c2988d5e04adf3a064f4ae34a93bfadeed3fceb6ae43`.

- **Calls that matter.** A call matters if its real result shows at least one of these: a verdict, an error or refusal, a wait of 30 seconds or more (a timeout counts), or another agent's activity. The plan's Appendix A states these rules. The rule's error rate was **not measured**: see "Known deviations" below.
- **Kinds of tool.** Every call is sorted into one of four kinds: quick, slow, depends on others, or waits its turn. Bare `sleep` and `wait` calls are excluded. The plan's Appendix A gives the rules.
- **Key facts.** For each call, `key_facts()` lists the facts that matter in the real output:
  - whether it passed or failed;
  - the kind of error, and roughly where;
  - key numbers, names, owners and phrases.

  A call with nothing notable gets one fact: "no error shown". `match_facts()` checks each fact against the auditor's predicted output, after removing harness-specific wrapping.
- **Pass or fail.** `verdict()` reads the real output and the predicted output the same way. It is told the command, so a proof check that exits cleanly counts as a pass, and a search that finds nothing is not a failure.

### Drawing the cases

- **Code and seed.** Cases are drawn by `src/swarmbench/studies/auditor/cases.py`, with seed 20261026. The result is `cases.parquet` (its draw is identified by `draw_id` `a4f573da53de`), with checksum (sha256) `a03d39696b5278713cfce04398d52937af3eb124bc6a81bf270ab78ed0182adc`.
- **The headline cases** (twice the plan's, by the user's decision):
  - one step: 240 calls that matter, plus 30 that don't;
  - several steps: 64 chains of 8 steps, each with at least 3 calls that matter;
  - shared tool: 200 cases. Half come from things where jobs wait their turn or compete: the proof checker, the RL environment's grader, and processors that several agents' heavy jobs compete for (as in the plan's Appendix A, "waits its turn or competes"). The proof checker supplies at most half of this half. The other half come from the other shared things: boards and messages, shared files and checkouts, servers and locks.
- **Within each situation,** every scenario with enough calls gets an equal share, up to a cap. In the shared-tool situation, each half is spread equally over the scenarios that have that kind of shared thing. Variants of a scenario count as one (the `family` column).
- **The extra asks** (sizes as in the plan):
  - 80 chain steps also asked with the real past;
  - 40 shared cases also asked without the record of the other agents;
  - 20 one-step cases also asked with a long history;
  - 20 cases asked twice;
  - 40 frozen moments for the waiting-line forecasts.
- **Practice cases** come from different agents than test cases, in the same runs. No run is set aside for practice, so every scenario family keeps all its runs in the test set. Practice cases are never scored in the results.

### The auditor and its instructions

- **Model:** Claude Opus 5.5 (`anthropic/claude-opus-5-5`), effort "medium" (changed from "low" before any test case was run; see "Changes after the practice round". The model always thinks; effort is its only setting, and the temperature is the provider's default), with at most 8,000 output tokens per answer, thinking included.
- **Instructions.** The practice round compares two versions of the instructions in `prompts.py`: "a" (the first draft: the machine's description and a fixed answer format) and "b" (the alternative: told to work out the machine's state, including other agents' use of shared resources, before answering, and that success is not the default). The chosen version is "a". It is `src/swarmbench/studies/auditor/prompts.py`, and its text has checksum `bd43eb0775c7bcb88d6abbe2a8f97f2a58b20dd9def4445d47d0b899025e4943` (sha256 of `instructions("a")`, 1,511 characters, answer format included). The choice rule was fixed before the practice round: keep the version with more hits on the practice calls that matter. If they tie, keep the one with the smaller typical timing error.
- **No scenario-specific coaching.** The instructions are the same for every scenario and contain no hand-written facts about any one scenario. What the auditor knows about a scenario comes only from its description and the agent's history.
- **Context.** The auditor sees:
  - a description of the scenario and the machine;
  - the agent's last 8 commands and their outputs;
  - in the shared-tool situation, the record of what the other agents did.

  The sizes are given in the plan.

### How each answer is scored

The code is `src/swarmbench/studies/auditor/score.py`.

- **Output hit.** A case is a hit when every key fact is right. A drawn case with no answer, a call that failed after its retries, or an answer that could not be read counts as a miss. Two kinds of case are not run and are left out of every result, with their numbers reported: cases the spending cap stopped before they were asked, and later steps of a chain after a step that failed even after retries (so a chain cut short can't look like drift). A case whose real output is missing has no facts to check, so it is left out of the output results; it is counted and reported.
- **Timing error.** The error is |ln(predicted time / real time)|, with times under one second counted as one second.
  - A command that hit its time limit got a result ("timed out") after about the limit. It counts as finishing then, and it is a call that matters.
  - A command that never returned (about 2% of all commands and 2.8% of proof checks, mostly checks still waiting when a run ended) has no real time. It is left out of the timing results, and its share is reported.
  - If the auditor gave no time, or said "never returns", for a command that did finish, the error is infinite. It counts as maximally wrong.
- **Commands timed to the end of a shared turn.** Sometimes the duration was measured as the time until the agent's next request (`timing_source` = `next_request`), and that request came after several commands issued together (`turn_calls` > 1). Then the duration times the slowest of those commands, not this one. These commands are left out of the timing headline, and the headline is re-run with them included as a sensitivity check.
- **Time band.** Under 60 seconds is "seconds"; 60 seconds or more is "minutes"; a command that never returned is "never". The answer is in the right band if its band matches the real one.
- **False pass.** The real result failed, but the auditor's result reads as a pass.
- **Will it wait** (shared tool). The auditor said whether, because others were using the same shared thing, the result would take 30 seconds or more. It really waited if it took 30 seconds or more, or never returned.
- **Background tasks.** The real time of a command run as a background task is until the task finished, not until the agent next looked, and the auditor is asked for exactly that.
- **Self-contradiction candidates** (chains). These are found by two rules about the same command run twice in a chain, where the auditor gave different outputs:
  1. The real outputs of the two runs were identical.
  2. The command only reads, and no step in between could have written to what it reads.

  A cheap model, Claude Haiku 5.5, also flags candidates (`src/swarmbench/studies/auditor/flags.py`). It sees each chain's commands and the auditor's answers, but not the real outputs, and replies with the two steps, a short exact quote from each, and a reason. A flag is kept only if both quotes appear in the answers shown. Its calls go through the same budget guard and spending ledger as the auditor's, and count toward the same cap. All candidates, from the rules and the model, go into one table and are confirmed or rejected by hand, without looking at whether the auditor was right. A candidate is confirmed only if nothing in between could explain the change.

### The lines

- **Output matches** if the share of calls that matter with every key fact right is shown to be above 80%. It **doesn't match** if it is shown to be below 80%.
- **Timing matches** if the typical (median) timing error is shown to be under a factor of 2. It **doesn't match** if it is shown to be over a factor of 2.
- Otherwise, the result is **can't tell**.

### The statistics

The code is `src/swarmbench/studies/auditor/analysis.py`, with random seed 20261026 and 10,000 bootstrap redraws.

- **Which cases.** Each headline result uses the test cases of its situation that matter, in their main form. Chains include their first step. Calls whose key facts say nothing beyond "no error" and account names (`content_facts` false in `labels.parquet`, about 3% of headline cases) are left out of the headline and reported apart, because an answer can get them right without knowing anything about the command.
- **Every scenario family counts equally.** Variants of a scenario count as one family (the `family` column). For output, the headline figure is the average of the shares' hit rates. For timing, it is the median error with each case weighted by one over its share's number of cases. The same weighting is applied in every bootstrap redraw. Beside each headline figure, the report shows the figure with every case counting equally. The parts are not reweighted, except where they are per scenario anyway.
- **Thin families are pooled (a rule, not a list).** In the final draw this pools the converter cutover and impossible maths into "other" for one step and the shared tool. In the several-steps situation it pools the alder quotes, bracken release, converter cutover, fenwick routing and turf war (impossible maths has no chains), leaving 4 shares: the proof conference, rival swarms, the RL coding environment and "other". The rule: for each situation, from its drawn test cases in their main form, a family with fewer than 2 runs is thin. In the several-steps situation, a family with fewer than 3 runs or fewer than 3 chains is also thin. The stricter rule for several steps is the user's decision, taken after simulation showed that chain families with 2 runs gave ranges that were too narrow (see "How precise the answers will be"). All thin families of a situation are pooled into one share, "other": its cases count equally within it, it gets one equal share like any family, and its runs are redrawn together in the bootstrap. A family on its own with 1 run has no run-to-run spread to redraw, so its range would be too narrow; pooling gives the redraw something to vary. If only one family is thin, it keeps its own share. The report lists which families were pooled in each situation.
- **Ranges.** The ranges are 95% intervals from a two-stage bootstrap, redrawn 10,000 times. In each share (a family, or the pooled "other") with k runs, k − 1 runs are redrawn with replacement. Redrawing all k understates the spread by a factor (k − 1)/k, which matters when a share has only 2 or 3 runs; drawing one fewer (the rescaled bootstrap of Rao and Wu) removes that bias for estimates that are averages within a share. A share with one run redraws that run. Then, in each drawn run, its agents (or its chains, in the several-steps situation) are redrawn with replacement. All cases of a drawn agent or chain come along together. This is a change from the plan (see the next section).
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
  - **the content-free yardstick:** the score of an answer that knows nothing about the command (aud-rules' `content_free_answer`: every account named in what the auditor was shown, marked "ok", then PASS and a clean exit), overall and per scenario family. The auditor's output score is read against it. With the current key-fact rules, it scores about 9% on the headline calls before family weighting (one step 9%, shared tool 11%); the report gives it with families weighted equally too;
  - calls whose facts carry no content (left out of the headline, see above);
  - the waiting-line forecasts against the checker program. This is a result for the proof conference only (no other scenario has a checker with known rules), and it is labelled that way, not as a result about tools in general;
  - calls that don't matter;
  - cases asked twice.

  Where a part has a test, its p-value goes into one Benjamini-Hochberg correction over all the parts, at 10%.
- **One scenario family left out.** Every headline result is computed again without each scenario family in turn, especially without the proof conference, which has the most commands. For each, the report gives the estimate, its range, and the label it would get: its new test replaces the original in the same Holm correction, with the other five unchanged. If any label changes, the report says so plainly at the top of that section. This is a pre-registered sensitivity check; the headline labels themselves come from all families.
- **Paired comparisons.** These are the same commands asked two ways: real past against own past, with against without the record of the others, and long against short history. Several pairs can come from one chain or one agent, so they are not independent. The tested p-value therefore comes from the same clustered bootstrap as the ranges: the paired differences are redrawn with whole chains (or agents within runs) together, and the p-value is the two-sided share of redraws on the other side of zero. McNemar's exact test (hits) and the Wilcoxon signed-rank test (timing errors), which treat pairs as independent, are reported beside it as the plan's checks.
- **Drift.** For each chain, the change is the error rate on the second half of its steps minus the error rate on the first half. The change is averaged over chains and tested by flipping the sign of whole chains. This uses **all scored steps** of the test chains; the same measure on calls that matter alone is reported alongside. A logistic regression of error on step number is a check. It is conditional on the chain, so each chain has its own baseline.

## Changes from the plan, and why

Changes 1 to 4 come from checks made before any auditor answer existed. Changes 5 to 8 are the user's decisions, taken after seeing those checks.

**1. Ranges also redraw runs.** The plan says to redraw "whole agents together within their run". I simulated the real run structure: 9 scenarios with 1 to 14 runs each, and cases spread equally over scenarios. Under that structure, the plan's way gives "95%" ranges that hold the truth only 78% of the time when runs differ from each other, and 86% even when they don't. Many runs supply only one or two agents, and a run with one agent adds no spread at all. The two-stage redraw holds the truth 88–94% of the time. It cannot reach 95% when runs differ, because some scenarios have only one or two runs. Its ranges are about 35–40% wider. Appendix A has the comparison.

**2. Drift is tested on all steps.** The plan expects a rise from 1 in 5 steps wrong to almost 1 in 2 to be "detected almost always", and a rise to 1 in 3 about 60% of the time. With only the 4 or so calls that matter per chain, simulation detects these rises 37–51% and 12–17% of the time. With all 8 steps, it detects them 72–93% and 18–30% of the time. Every chain step is scored against reality anyway, so the test uses all of them. Even so, only a large rise is likely to be detected.

**3. Timeouts are results.** The plan says about 40% of proof checks have no finish time. Preparation found that only 2.8% of proof checks (about 2% of all commands) never got a result. The plan's figure most likely counted checks that hit the 300-second limit. Those do get a result ("timed out") after about 300 seconds, and they are scored like any other command. **Fixed rule, agreed by the user:** a timeout is a real outcome. It is a call that matters (a long wait), and its duration is the limit. Commands that never returned are reported as a separate share.

**4. Commands timed to the end of a shared turn.** Including them would credit or blame the auditor for another command's duration. **Fixed rule, agreed by the user:** rows timed by the next request (`timing_source` = `next_request`) where that request followed several commands (`turn_calls` > 1) are left out of the timing headline. The headline timing results are reported again with them included, as a sensitivity check.

**5. Twice the headline cases.** At the plan's sizes, the output labels would be less sharp than the plan claimed (see "How precise the answers will be"). The user decided to double the headline cases: 240 one-step calls that matter, 64 chains and 200 shared-tool cases. The other sizes are unchanged. The spending cap rises from $35 to $45.

**6. Shared-tool cases split by kind.** The plan expected the proof checker to supply most shared-tool cases. The user decided that half come from waiting-line tools (the proof checker and the RL environment's grader) and half from the other shared things, each half spread equally over the scenarios that have them. This keeps one tool from dominating the result. Results for the two halves are reported as parts.

**7. Every scenario family counts equally.** The plan pooled all cases, so a scenario with more cases would count more. The question is about tools in general, and the proof conference holds 73% of all commands. So each family gets equal weight in every headline figure and every bootstrap redraw. The pooled figure is shown beside it, so a reader can see when the two differ.

**8. Leaving one scenario family out.** A headline label that holds only because of one scenario would not say much about tools in general. Each headline result is therefore computed again without each family in turn, with the label it would then get. A label that changes is reported plainly. This check does not change the headline labels.

## What the free yardsticks found

Before any auditor answer, the free yardsticks replaced several of the plan's guesses with measurements (`src/swarmbench/studies/auditor/yardsticks.py` and `queue_sim.py`; figures in `runs/_studies/auditor/yardstick_summary.json`). They set what the timing results can be compared with.

- **Proof-checker slots per run.** These are read from each run's machine settings and confirmed by agents' own listings where possible. Four early runs had 1 slot. The others had 9 (the run where 30 agents shared 9 slots), 32, 6, 6, 6 and 12.
- **The 300-second limit** is Antigravity's command limit, not the proof checker's: Antigravity stops any command after 300 seconds in total, waiting included, and kills it, which frees its slot. The checker itself has no limit.
- **How much real timing varies by itself.** The same command with the same output, run more than once, takes typically 1.0× the same time: 1.04× for calls that matter, 1.05× for proof checks. One in ten proof-check repeats differs by 2.25× or more. So the factor-2 line is far above what reality itself varies by, except for waiting-line tools under load.
- **The timing rule of thumb.** This predicts a command's time from the same or similar commands in other runs, adjusted for how busy the machine was. It is typically 1.3× off on all calls, 1.7× on calls that matter, and 1.9× on waiting-line tools. On quick, slow and other-agent commands it is typically exact. An auditor whose typical timing error is above about 1.7× on calls that matter does worse than this simple rule.
- **The proof-checker program.** This is a short program that follows the checker's real rules. In the five runs where checks rarely waited, it reproduces the real waits exactly and agrees on every timeout. In the five jammed runs (1 slot in four of them; 9 slots for 30 agents in the fifth), its waits for single checks are typically 1.3× to 4.6× off, and it agrees on whether a check hit the 300-second limit 60–91% of the time. Part of that error comes from checking times it has to estimate, because the logs don't record when a waiting check got its slot.

## How precise the answers will be

These figures come from simulating the study on the **actual drawn cases** (`cases.parquet`, draw `a4f573da53de`): the same families, runs, agents, chains and cases, with the pooling rule and the redraw exactly as fixed above. Only the outcomes are simulated, with a known truth. Two sets of assumptions are used for how alike grouped cases are, because the real values are only known after the run:
- the independent review's: on the log-odds scale, run differences of 0.5 and agent or chain differences of 1.0 to 1.5 (standard deviations);
- this study's earlier ones: run 0.5, agent 1.6, chain 3.5.

Both put family differences at 0.5. Appendix A has the details.

**Do the 95% ranges hold the truth 95% of the time?** Share of simulated studies where the range held the truth (200 each):

| Situation | Output: review, 1.0 | Output: review, 1.5 | Output: earlier | Timing |
|---|---|---|---|---|
| One step | 96% | 96% | 95.5% | 99.5% |
| Several steps | 93.5% | 96% | 95.5% | 98% |
| Shared tool | 99% | 98.5% | 98% | 99.5% |

The ranges hold the truth about 95% of the time or more in all three situations. The shared tool's ranges are somewhat wider than they need to be.

**Several steps needed a stricter pooling rule.** With only the general rule, chain families with 2 runs (alder quotes, bracken release, fenwick routing, turf war) and the converter cutover (2 chains from 1 run) kept their own shares, and the several-steps ranges held the truth only 91.5–96% of the time (output) and 92.5% (timing). The user decided that, in this situation only, a family with fewer than 3 runs is also thin. These five families are then pooled into one "other" share. The figures above are with that rule. The cost is that the several-steps figure gives 4 equal shares, not 8.

**How sharp are the labels?** Each figure is the true value at which a result gets the right label at least 80% of the time. For example, "92%" under "matches if right at least" means: an auditor truly right on 92% of the calls that matter is labelled "matches" in at least 80% of studies like this one. Each cell gives the range over the three assumption sets.

| Situation | Headline cases | Output "matches" if right at least | Output "doesn't match" if right at most | Timing "matches" if typically off by at most | Timing "doesn't match" if typically off by at least |
|---|---|---|---|---|---|
| One step | 240 | 92–93% | 58–61% | 1.6× | 3.2× |
| Several steps | 64 chains, 344 calls that matter | 90–94% | 59–65% | 1.6× | 2.8× |
| Shared tool | 200, half waiting-line tools | 93% | 58–61% | 1.55× | 3.3× |

So the study separates clearly good from clearly bad. An auditor right on more than about 94% of the calls that matter, or under about 58%, will very likely get its label. One in between may come out "can't tell". These figures are a little wider than the ones in earlier drafts of this file. Those drafts used an invented case structure and the textbook redraw, and their ranges were too narrow (Appendix A). The plan's own figures (89–91% / 61–66%) did not hold even for the plan's smaller study. Even under the plan's own assumptions, its thresholds give the right label only 52–72% of the time, not 80%.

**Timing:** a typical error of 1.5× is labelled "matches" almost always, and one of 3.5× is labelled "doesn't match" almost always.

**Paired comparisons and drift.** Their sizes are unchanged. With McNemar's test at 5% and independent pairs (Appendix A):
- 80 pairs detect a 30-point difference 99% of the time, and a 20-point difference 82% of the time;
- 40 pairs detect a 30-point difference 80–83% of the time.

Pairs from the same chain make the tested, clustered version somewhat less sensitive than this.

With 64 chains, drift from 1 in 5 steps wrong to 1 in 2 is detected 96% of the time, and to 1 in 3 only 41% of the time (all 8 steps scored; with the logistic check, 99.7% and 52%; Appendix A).

## Spending

All paid calls go through one hard cap enforced in code (the runner's budget guard and its spending ledger, which counts every batch). The spending happens in two steps:

1. **The practice round runs first**, live, with a hard cap of **$6**. It compares the two instruction versions on the practice cases and picks one by the rule above. It also measures how long the auditor really thinks, which the cost estimate could only guess.
2. **The main test batch's cap** is then set from the practice round's measured cost per call, and approved by the user before the main batch runs: $75 for the whole study (approved by the user on 2026-10-26; $6.23 was already spent on the practice round and the effort probe). The Haiku contradiction flags count toward the same cap.

The study's overall limit discussed so far is $45, for the practice round and the main batch together.

## Known deviations

**The hand check of "calls that matter" was not completed.** The plan says the rule is checked by hand on 60 random calls and the error rate is reported. That did not happen in full:
- The user looked through part of the 60-call page and found every label they checked correct, but did not finish it. The check was informal, and the number of calls looked at was not recorded.
- aud-rules checked 20 calls and found 1 error, which has been fixed.

So there is **no measured error rate** for the rule, and none is reported as one. The results describe the calls the rule selects. If a full hand check is done before the test run, its rate is added here as a dated note.

## Changes after the practice round

Recorded on 2026-10-26, after the practice round and before any test case was run. The rules above were committed first, in 009cd3a ("Auditor pre-registration: rules fixed before the practice round").

- **Instruction version.** Chosen by the pre-registered rule: on the 34 practice calls that matter, version "a" got 14 hits and version "b" 11, so "a" is kept.
- **Effort, changed from "low" to "medium".** "Low" had been chosen to save money, not tested, and the user judged that it could understate what the model can do. Version "a" was asked the 46 practice questions again at medium effort ($2.36). It got the same 14 hits of 34, with about 360 thinking tokens per answer instead of about 70, and cost 29% more per question. The main batch runs at medium. The practice comparison of "a" and "b" was made at low effort, and that is not redone.
- **Spending cap.** $75 for the whole study, set from the measured cost per question, approved by the user.
- **A scoring bug found in the practice round.** `score.py` keeps one answer per case, so it merged the two instruction versions' answers in the practice batch. The comparison above was scored on each version's answers separately. The test batch uses one version, so this does not affect it. The bug is fixed separately.

## What counts as a deviation

Once this file is committed, each of the following is a deviation. It is reported in the results, with its reason and, where possible, the result both ways:

- any change to the commands table, the labels, the case draw or its seed, the auditor model, its settings or its instructions;
- any change to `score.py` or `analysis.py` after the commit above, except a fix that doesn't change any number. A fix that changes numbers is reported with both versions;
- leaving out, re-asking or replacing any test case. Exception: a call that failed for a technical reason, such as a timeout or a provider error, may be retried up to 3 times. The last readable answer is used, and the number of retries is reported;
- changing a line, a test, the correction methods, the bootstrap grouping, the seed or the number of redraws;
- reporting any part not listed above as if it had been planned. New analyses are welcome, but they are labelled exploratory;
- changing the hand-confirmation rules for self-contradiction flags after seeing any flag.

## Things to fill in before committing

Filled when the file is committed, before the practice round (no paid call needed):
- the date and the commit hash (which also fixes the version of all the code);
- a check that the three data checksums and the `draw_id` above are unchanged (they were taken on 2026-10-26).

Filled after the practice round, and only these:
- which instruction version was chosen ("a" or "b"), and the checksum of its rendered text;
- the main batch's spending cap, approved by the user.

Everything else is filled in above.

## Appendix A: simulation checks of the statistics

All of these can be re-run with `uv run python -m swarmbench.studies.auditor.simulation <check>`. The checks are `actual` (the drawn cases), `coverage`, `plan`, `drift` and `paired`. The code is `src/swarmbench/studies/auditor/simulation.py`. Each check takes a few minutes to about twenty.

**Coverage and precision on the actual draw** (`actual`). The study is simulated on the exact headline cases of `cases.parquet` (draw `a4f573da53de`), with the pooling rule and the redraw as fixed. Only the outcomes are simulated:
- **Output.** Each family has a fixed effect (standard deviation 0.5, drawn once). Each run and each agent (or chain) has a random effect. All are on the log-odds of a hit. The truth is the estimand: the average over shares of each share's expected hit rate over new runs and agents.
- **Timing.** The signed log error is normal. Run differences make up 15% of its variance, and agent differences 25% (chain differences 50%). Its typical absolute value is the truth.
- **Labels.** Labels use Holm's strictest step (0.05/6). Each figure comes from 200 simulated studies with 1,000 redraws each. Coverage is measured at 85% hits and at 2× off.

| Situation | Assumptions (run / agent or chain sd) | Output range holds truth | Timing range holds truth | Output "matches" if ≥ | Output "doesn't" if ≤ | Timing "matches" if ≤ | Timing "doesn't" if ≥ |
|---|---|---|---|---|---|---|---|
| One step | review: 0.5 / 1.0 | 96% | 99.5% | 91.8% | 60.7% | 1.58× | 3.19× |
| One step | review: 0.5 / 1.5 | 96% | 99.5% | 92.7% | 58.3% | 1.58× | 3.19× |
| One step | earlier: 0.5 / 1.6 | 95.5% | 99.5% | 92.8% | 58.5% | 1.58× | 3.19× |
| Several steps (4 shares) | review: 0.5 / 1.0 | 93.5% | 98% | 90.4% | 64.9% | 1.62× | 2.79× |
| Several steps (4 shares) | review: 0.5 / 1.5 | 96% | 98% | 91.5% | 63.2% | 1.62× | 2.79× |
| Several steps (4 shares) | earlier: 0.5 / 3.5 | 95.5% | 98% | 93.8% | 59.0% | 1.62× | 2.79× |
| Shared tool | review: 0.5 / 1.0 | 99% | 99.5% | 92.7% | 60.7% | 1.54× | 3.32× |
| Shared tool | review: 0.5 / 1.5 | 98.5% | 99.5% | 93.3% | 58.9% | 1.54× | 3.32× |
| Shared tool | earlier: 0.5 / 1.6 | 98% | 99.5% | 93.4% | 58.4% | 1.54× | 3.32× |

(The timing assumptions don't depend on the output ones, so timing figures repeat.)

**Why one fewer run is redrawn.** On the same draw, redrawing all k runs of a share (the textbook bootstrap) holds the truth only 91–93% of the time for one step, 88–89.5% for several steps and 92.5–94% for the shared tool (output), and 89–96% for timing. Redrawing k − 1 gives the coverage above.

**The stricter pooling rule for several steps.** Before it, the several-steps situation had 8 shares (only the converter cutover was thin, and it kept its own). Its output ranges held the truth 91.5% / 93.5% / 96% of the time (the three assumption sets), and its timing ranges 92.5%. The labels' thresholds were 89.8–92.9% / 58.1–66.1% and 1.60× / 2.90×. With the rule (4 shares), they are as in the table above.

**Choosing how to redraw, before the draw existed** (`coverage`). An early check used an invented structure based on the plan's run counts, with one-step cases spread equally over 9 scenarios and runs that differ (run sd 0.7). It asked how often each way of redrawing holds the truth (300 simulated studies):

| How cases are redrawn | Runs differ | Runs don't differ | Typical width |
|---|---|---|---|
| Agents within their run (the plan) | 78% | 86% | ±6 points |
| Agents within their scenario | 83% | 92% | ±7 points |
| Whole runs within their scenario | 75% | 76% | ±5.5 points |
| Runs within scenario, then agents within run (chosen) | 88% | 94% | ±8 points |

The same invented structure guided the decision to double the headline cases. Its precision figures are replaced by the ones on the actual draw above.

**The plan's own precision claims, under its own assumptions** (`plan`). This uses the plan's design effects (1.5× for agents, 2.5× for chains), simple groups of 3 or 4 cases, and the plan's way of redrawing:

| Situation | Truth | Plan: chance of the right label | Simulated |
|---|---|---|---|
| One step | 89% right | 80% (implied) | 56% |
| One step | 66% right | 80% (implied) | 71% |
| Several steps | 91% / 61% right | 80% (implied) | 52% / 72% |
| Shared tool | 90% / 65% right | 80% (implied) | 56% / 64% |
| One step, timing | 1.5× / 4× / 3× | 98% / 95% / 65% | 100% / 100% / 94% |
| Several steps, timing | 1.5× / 4× | 73% / 67% | 99% / 100% |
| Shared tool, timing | 1.5× / 4× / 3× | 95% / 92% / 56% | 100% / 99% / 91% |

**Drift** (chains of 8 steps; the error rate rises in a straight line from the first step to the last; tested at 5%). With the plan's 32 chains:

| Steps scored per chain | Chains differ (log-odds sd) | 20% → 50%: halves test / logistic check | 20% → 33%: halves test / logistic check |
|---|---|---|---|
| 4 (calls that matter) | 0 | 37% / 51% | 12% / 17% |
| 4 | 1.0 | 39% / 47% | 13% / 15% |
| 8 (all steps) | 0 | 78% / 93% | 18% / 30% |
| 8 | 1.0 | 72% / 87% | 18% / 26% |

With the final 64 chains (chains differ, log-odds sd 1.0):

| Steps scored per chain | 20% → 50%: halves test / logistic check | 20% → 33%: halves test / logistic check |
|---|---|---|
| 4 (calls that matter) | 68% / 82% | 23% / 31% |
| 8 (all steps) | 96% / 99.7% | 41% / 52% |

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
