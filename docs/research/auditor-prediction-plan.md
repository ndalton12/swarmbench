# Can a simulating model predict what tools do?

Draft research plan, 2026-10-23, for review. Nothing here has been run, and no money has been spent.

## Summary

We study how AI agents behave when several of them share one computer. There are two ways to give them a computer. One is to run them on a real machine. The other is to have a second AI model pretend to be the machine: each time an agent runs a command, this model writes what the command would have printed. We call the pretending model the **auditor**. A pretend machine is cheap and flexible, but only useful if the auditor's answers are realistic.

This plan measures two things about the auditor's answers:

- **Output:** is what the tool prints right?
- **Timing:** is the time the tool takes right?

It measures them in three situations, which gives six results:

1. **One step, with the real past.** The auditor sees the real history up to a command and predicts that one command.
2. **Several steps, with its own past.** The auditor answers about 8 commands in a row. From the second one on, the history it sees contains its own earlier answers instead of the real ones. This shows whether errors build up, and whether it contradicts itself.
3. **A shared tool under load.** Several agents use the same thing at once: many agents waiting in line at a proof checker, a file two agents are editing, a busy service. The auditor sees what all of them were doing and predicts one agent's result.

The headline results count only **calls that matter**: commands whose result an agent is likely to act on, such as a pass or fail, an error, a long wait, or a sign of another agent's activity. Everything else is reported separately.

The test material already exists. Our test bench, swarmbench, has 37 recorded runs with real AI agents across 9 scenarios, holding about 29,000 logged commands with what each printed and how long it took. The commands are replayed from those records. **No agents are run**, so the only cost is the auditor's own answers.

The pass and fail rules are fixed before any results are seen. With Claude Opus 5.5 as the auditor, the recommended study costs about **$30**. A bare version costs about $17.

This study is a cheap way to find which part of a pretend machine breaks: the output, the timing, shared resources, or drift over several steps. It cannot show by itself that a whole simulated run behaves like a real one. That needs full simulated and real runs compared side by side, which is the subject of a separate plan.

## Background

**swarmbench** is our test bench for studying groups of AI agents. Each agent gets its own user account on one shared Linux machine. The agents work on a task in parallel, and can see and get in each other's way. A **scenario** is one such task with its setting, for example a team migrating a codebase, or researchers proving maths problems. The record of each run holds every command each agent ran, what it printed, and when it started and finished.

**Pretend machines.** Some testing tools skip the real machine and have an AI model play it. Petri, a widely used open-source testing tool, works this way. The agent can't tell it is talking to an auditor, unless the auditor gets something wrong.

**Why this matters.** We are deciding how much of an agent's world must be real. A pretend machine is cheap and can be anything. A real machine is exact, but takes work to build. In one earlier small comparison, agents on a pretend machine took 5 to 10 times fewer actions per minute than agents on a real one. Behaviours that real agents showed after long waits at a shared tool mostly didn't appear: retrying, working around the waiting line, killing other agents' jobs. We don't know which part of the pretence failed. Each answer points to a different fix:

| If the auditor gets this wrong | The fix |
|---|---|
| Output | Keep tools real |
| Timing | Give the auditor timing facts or a clock |
| Shared resources | Track them with a small program instead of the auditor |
| It drifts over several steps | Re-anchor it to real facts regularly |

## What this study can and cannot show

**It can show** which of those parts breaks, for which kinds of tool, at low cost. It uses records we already have, and every answer is checked against what really happened.

**It cannot show** that a whole pretend run reproduces real behaviour. Small errors can matter a lot, or not at all, depending on what agents do with them. Answering that needs complete simulated runs compared with matched real runs, as planned in `fidelity-ladder-experiment.md`. This study tells that larger one where to look, and which fixes to build first. It also feeds the trade-off write-up `simulated-vs-hybrid-environments.md`.

## The design: two measures in three situations

|  | 1. One step, real past | 2. Several steps, own past | 3. Shared tool under load |
|---|---|---|---|
| **Output right?** | headline result | headline result | headline result |
| **Timing right?** | headline result | headline result | headline result |
| Test cases (calls that matter) | 120 | about 128 (in 32 runs of 8 steps) | 100 |

### The two measures

- **Output.** For each case, the facts that matter in the real output are listed in advance by fixed rules:
  - whether it passed or failed;
  - the kind of error, and roughly where (within two lines);
  - key facts such as a number, a file or process name, who owns something, or "permission denied".

  A case is a hit if the auditor gets every listed fact right. Scoring is done by rules, not by another AI model acting as judge, because a recent study found such judges biased in the simulator's favour.
- **Timing.** This is the time from the agent running the command to the result reaching it. The error is how many times too fast or too slow the auditor was: predicting 20 seconds for a 10-second command is "2 times off". Times under one second count as one second, since an agent can't notice the difference.

### Situation 1: one step, with the real past

The auditor gets:
- a short description of the scenario and the machine;
- the agent's last 8 commands and their real outputs;
- the next command.

It predicts what that command prints and how long it takes. It never sees anything after that command.

### Situation 2: several steps, with its own past

A pretend machine has to live with its own earlier answers. This situation tests that.

1. Pick a starting point in a real run. Take that agent's next 8 real commands.
2. The auditor answers the first command with the real history in front of it, as in situation 1.
3. For each later command, the history it sees has the auditor's own earlier answers in place of the real outputs.
4. Every step is scored against reality.

No agent is involved: the commands come straight from the record.

Two further results come from these chains:
- **Drift:** whether errors become more common from the first steps to the last ones.
- **Self-contradiction:** whether the auditor contradicts something it said earlier. Example: it said a file contains one thing, then shows different contents for an unchanged file. Contradictions are found by rules for repeated commands on unchanged things, plus a cheap AI model (Claude Haiku 5.5) that flags candidates. Every flag is confirmed by hand.

For 80 chain steps that matter, the same command is also answered with the real past. That gives a direct, same-command measure of how much having its own past costs the auditor.

The starting points are picked so that each chain contains at least three calls that matter.

### Situation 3: a shared tool under load

These are moments when several agents used the same thing within a few minutes, and the result depended on that. For example:
- **The proof checker:** in one scenario, all agents check maths proofs with one shared command. Each check needs about one processor core and 2.5 GB of memory, so only a fixed number run at once. Each of those places is called a **slot**, and other checks wait their turn. In one real run, 30 agents shared 9 slots, waits grew from seconds to minutes, and some agents killed others' checks.
- **A grading service** that runs each submitted solution as a separate job.
- **A shared code checkout,** where two agents edit the same files.
- **Locks,** where one agent's program holds something another needs.
- **Busy services and processors:** a server another agent runs, or heavy jobs competing for the same processors.

The auditor gets the scenario description, this agent's recent commands, and a **record of the others**. The record lists what every relevant agent did with the shared thing in the previous five minutes, and what is still running, all taken from the real logs. It predicts this agent's output and wait. This record is perfect bookkeeping, so it shows the best a pretend machine could do if it tracked everyone accurately. For 40 of the cases, the auditor is also asked without the record, to show how much keeping track of others matters.

**A closer look at waiting lines.** The proof checker's rules are known exactly, so it is the best place to test whether an auditor can forecast a line building up. We freeze 40 moments of real runs, at least 5 minutes apart, and show the auditor every agent's recent checks, what is running and waiting, and how many slots there are. It forecasts:
- the typical wait over the next 10 minutes;
- how many checks will be waiting 5 and 10 minutes later;
- whether checks will start hitting the 5-minute limit.

These forecasts are reported as part of situation 3, not as a headline.

## Calls that matter

Most commands an agent runs are routine. A pretend machine can get a file listing slightly wrong without changing anything. The headline results therefore use only calls whose result an agent is likely to act on.

**The rule.** A call matters if its real result shows any of:
1. **a verdict:** passed or failed, accepted or rejected, tests passing or failing, or a command ending in failure;
2. **an error or refusal:** an error message, "permission denied", "operation not permitted", or "not found";
3. **a long wait or contention:** the result took 30 seconds or more, timed out, or reported something busy or locked;
4. **other agents' activity:** other users' processes, files, posts, messages or code changes appear in the output.

The rule looks only at the real result, so it is applied before the auditor sees anything. It is checked by hand on 60 random calls, and the error rate is reported. All other calls are reported separately as secondary results: 30 of them are scored in situation 1.

## Where the cases come from

**Real runs only.** Some run folders are test runs with a stand-in model that only replays fixed replies. They are skipped. That leaves 37 runs with real AI models:

| Scenario | What the agents do | Real runs | Logged commands | Shared things |
|---|---|---|---|---|
| Proof conference | Prove maths problems with a shared proof checker | 9 | 21,500 | the checker's waiting line, a message board |
| Rival swarms | Two teams plan routes | 14 | 4,680 | processors, a board, shared folders |
| RL coding environment | Fix coding tasks, graded by a service | 4 | 1,590 | the grading service |
| Alder quotes | Pricing work | 2 | 610 | messages, shared files |
| Turf war | Several agents share one code checkout | 2 | 380 | the checkout, a server and its port |
| Fenwick routing | Write a routing report | 2 | 290 | messages, shared files |
| Bracken release | Prepare a billing release | 2 | 140 | shared files |
| Converter cutover | A code migration | 1 | 70 | the checkout, test runs |
| Impossible maths | A task that can't be fully done | 1 | 40 | a board |
| **All** | | **37** | **about 29,300** | |

The agents ran under three **harnesses**, the programs that run an agent's model and give it tools: Claude Code, Codex and Antigravity. The runs used about a dozen agent models.

The eight turf war runs from 2026-10-21 have empty folders on this laptop. If their records are on the cloud machine, copying them over would add eight runs.

**Drawing cases.** Cases are drawn at random with a fixed starting seed, so the draw can be repeated exactly. Within each situation, every scenario with enough calls gets an equal share, up to a cap. That stops the proof conference, which holds 73% of all commands, from dominating. It still supplies most of the waiting-line cases in situation 3, because few other scenarios have such a tool.

For reporting, every call is also sorted by rule into one of four kinds:
- quick, predictable commands (reading, listing, editing files);
- slow computations (tests, compiles, scripts);
- commands that depend on other agents (process lists, kills, boards and messages, shared code history);
- tools where jobs wait their turn or compete.

The sorting rules are in Appendix A.

**A practice round, kept separate.** Before the real test, we try two versions of the instructions given to the auditor, our first draft and one alternative. We try them on a small separate set of practice cases: 20 single steps, 2 chains and 10 shared cases. We keep the version that does better and freeze it, then score only on cases never used for practice. This gives the auditor a fair chance, and keeps the score honest, because the instructions were never tuned on the cases that count. Practice cases come from different agents than test cases, and a whole run is used for practice where a scenario has several.

The practice round can be skipped, using one sensible set of instructions instead. That saves about $3. But then a poor result can't rule out that better wording would have fixed it.

## What the auditor is given

**Context** is the text the auditor reads before it answers. To keep costs low, it is short:
- a description of the scenario and the machine, about 3,000 tokens (a token is a piece of a word; 3,000 tokens is roughly 2,000 words), the same for every case from a run;
- the agent's last 8 commands and outputs, about 6,000 tokens;
- in situation 3, the record of the others, about 4,000 tokens more.

The auditor answers in a short fixed format: the predicted output, the predicted time with a likely range, and, for shared tools, whether the command will have to wait.

**Short context is a limitation.** A fact the agent learned 50 commands ago may be missing. So 20 situation 1 cases are also asked with a long history, about 30,000 tokens. With so few cases this can only reveal a very large effect, about 45 points in the share of hits. But it shows whether the short window is hiding something obvious.

## The yardsticks

An auditor's error only means something next to what is achievable. Two yardsticks are used throughout. Both are free.

- **How much reality varies.** Many commands were run more than once with the same text and the same result, across runs of a scenario: a test suite, a status command, a proof file. The spread of their times shows how much real timing varies on its own. Proof files can also be re-run offline through the real checker. That confirms the output repeats exactly, and measures how much checking time varies by itself.
- **A simple rule of thumb, written as a program.** For timing, it predicts the typical real time of the same command in other runs, adjusted for how busy the machine was. For the proof checker, a short program follows the checker's actual rules: a fixed number of slots, and waiting checks that retry every second, with the first to find a free slot winning. It uses each file's real checking time.

If an auditor does worse than a rule of thumb, a pretend machine should use the rule for timing and the auditor only for text.

## What counts as matching reality

These rules are fixed and committed to the repository, with a date, before any test case is run. Each of the six headline results is labelled **matches**, **doesn't match** or **can't tell**.

- **Output matches** if the auditor gets every key fact right in more than 80% of calls that matter, after allowing for chance. It **doesn't match** if that is shown to be under 80%. Why 80%: an auditor wrong on more than one in five results that agents act on would send them down false paths often enough to change a run.
- **Timing matches** if the typical error is shown to be under a factor of 2. It **doesn't match** if it is shown to be over a factor of 2. Why a factor of 2: what changes an agent's behaviour is mostly whether a result comes in seconds, in minutes, or not at all, and a factor-2 error usually keeps it in the right band. The earlier pace gap was a factor of 5 to 10.

"Shown" means the result holds even after allowing for chance. The next section says how far from the line the truth must be for that.

**Parts of the results.** These are reported with uncertainty ranges, but are not headlines:
- results per scenario and per kind of tool;
- pass-or-fail verdicts on their own;
- **false passes**, where the auditor says something succeeded but it really failed (these hand an agent credit it never earned);
- whether results land in the right time band (seconds, minutes, never);
- drift and self-contradiction along the chains, and the same-command comparison with the real past;
- the gain from the record of the others;
- the long-history check;
- the waiting-line forecasts;
- all calls that don't matter.

**Expected results, written down now:**
- **One step:** output matches for routine results, but not for verdicts on tests and proofs. Timing is borderline.
- **Several steps:** both are worse than one step, and errors grow along the chain.
- **Shared tool:** neither matches. The record of the others helps, and the proof checker program forecasts waits better than the auditor.

## How sure the answers will be

Each estimate comes with a range that the true value falls in 95 times out of 100, a **confidence interval**. Calls from the same agent, and steps in the same chain, tend to be alike. So the ranges are computed in a way that respects that grouping. Treating them as independent would make the ranges too narrow. Running six headline tests raises the chance that one looks significant by luck, so a standard correction keeps the chance of any false alarm across all six at 5%. Details are in Appendix B.

What the case numbers buy, in plain words:

| Result | Cases | Output: precision | Output: labelled "matches" if truly at least / "doesn't" if at most | Timing: chance of the right label |
|---|---|---|---|---|
| One step | 120 | about ±9 points (if 90% right) to ±13 (if 70%) | 89% / 66% | truly 1.5 times off: "matches" 98%; truly 4 times: "doesn't" 95% (3 times: 65%) |
| Several steps | about 128 in 32 chains | about ±11 to ±17 points | about 91% / 61% | truly 1.5 times: "matches" at least 73%; truly 4 times: "doesn't" at least 67% |
| Shared tool | 100 | about ±10 to ±15 points | 90% / 65% | truly 1.5 times: "matches" 95%; truly 4 times: "doesn't" 92% (3 times: 56%) |

**Parts:**
- **Drift.** With 32 chains, a rise from 1 in 5 steps wrong at the start to almost 1 in 2 at the end is detected almost always. A rise to 1 in 3 is detected about 60% of the time.
- **Same command, own past against real past** (80 pairs): detects a difference of about 30 points.
- **With against without the record of the others** (40 pairs): detects a difference of about 30 points.

So this first study separates clearly good from clearly bad, which is what the decisions need. It can't pin down small differences. The several-steps results are the least precise, because the steps within one chain are so alike.

## Cost

**How it is calculated.** Each answer is one call to the auditor. The provider charges per token, at different prices for what the auditor reads and what it writes.

**Prompt caching** means the provider stores text that repeats across calls, and charges about one-twentieth of the normal price to read it again. Calls from one run are sent together, so the stored copy is used before it expires (about five minutes). In a chain, each step re-reads the previous steps from the store.

Cost per call =
(repeated text × cache re-read price) + (new text × input price, or × cache-store price if it will be reused) + (answer × output price).

Prices are for Claude Opus 5.5, from OpenRouter's list saved in swarmbench (2026-10-23), in dollars per million tokens: $4 to read, $0.20 to re-read from the cache, $5 to store in the cache, and $20 to write.

| Call | Re-read from the cache | New text | Answer | Cost per call |
|---|---|---|---|---|
| One step | 3,000 | 6,000 | 500 | $0.035 |
| One step, long history | 3,000 | 30,000 | 500 | $0.131 |
| A chain step (average) | about 15,000 | 1,500, stored for the next step | 500 | $0.020 |
| Start of a chain | 3,000 | 6,000, stored | 0 | $0.030 |
| Shared tool, with the record | 3,000 | 10,000 | 500 | $0.051 |
| Waiting-line forecast | 3,000 | 5,000 | 400 | $0.029 |

**The recommended study:**

| Item | Calls | Cost |
|---|---|---|
| One step: 120 calls that matter, plus 30 that don't | 150 | $5.20 |
| One step, long history | 20 | $2.60 |
| Several steps: 32 chains of 8 steps | 256 steps, 32 starts | $6.10 |
| Same commands with the real past | 80 | $2.80 |
| Contradiction flags (Claude Haiku 5.5 at $0.10 to read and $0.50 to write per million tokens) | 32 | $0.10 |
| Shared tool with the record | 100 | $5.10 |
| Shared tool without the record | 40 | $1.40 |
| Waiting-line forecasts | 40 | $1.10 |
| Practice round (two instruction versions) | about 100 | $3.00 |
| Self-consistency: 20 cases asked twice | 20 | $0.70 |
| Storing scenario descriptions (about 100 run-and-version pairs × $0.015) | — | $1.50 |
| **Total** | **about 870** | **about $30** |

**How it scales:**
- **Bare version** (headline cases only: 120 one-step, 32 chains and 100 shared): about **$17**.
- **Without the practice round and the long-history check:** about **$24**.
- **Each extra 100 one-step cases:** about $3.50. **Each extra 10 chains:** about $1.90.
- **Longer answers:** if the auditor writes 1,500 tokens instead of 500, every call costs about $0.02 more, about $17 more in total.

Spending caps, approved before launch: $35 for this study.

## What the results would mean

| Result | Meaning for pretend versus real machines | Next step |
|---|---|---|
| Output fails at one step, mainly on verdicts | Tools that check work (tests, compilers, graders) must be real. Their verdicts drive what agents do next | Run checking tools for real. Let the auditor handle only what can't be real |
| One step is fine, several steps fail | The auditor is accurate but drifts on its own | Re-anchor it to real facts, for example by keeping files and command results real, or checking its answers against a stored record of the world |
| Timing fails, but a rule of thumb does well | AI models shouldn't keep time | Use a timing table or program, with the auditor writing only text |
| Shared tool fails without the record, passes with it | The auditor can work things out, but can't keep track of everyone | A small program keeps the shared state, and the auditor reads from it |
| Shared tool fails even with the record, and the checker program does better | Waiting lines and jams need to be computed, not imagined | Model shared resources in code, or keep them real |
| All six match | Pretend machines handle these tools well | The 5-to-10-times pace gap has another cause, such as how a simulation takes turns between agents. Look there, and in whole-run comparisons |
| Results differ a lot between kinds of tool or scenarios | Realism depends on the tool | Decide per kind of tool what must be real |

**Decision points:**
- If a headline result is "can't tell" or close to its line, run the follow-up below.
- If the waiting-line forecasts are borderline, run the optional load tests.

## Optional extensions

These are not part of the recommended study.

- **A bigger, more precise follow-up,** only if the first study is borderline. It doubles the headline cases and adds two more auditor models, GPT-6 Astra and Gemini 4 Argon. Cost: about $65.
- **Scripted load tests on the real proof checker.** No AI agents are involved. Small scripts each play one "agent": each sends real proof files from the logs to the real checker, waits for the answer, pauses for a realistic "thinking" time, and sends the next file. Running them at different combinations of agents and slots, several times each, measures real waits at loads no run has tried, and how much those waits vary.

  This needs a big machine: each check uses about one core and 2.5 GB of memory, so 30 checks at once need about 32 cores and 80 GB. The project's cloud machine has 32 cores and is kept running all the time anyway, so the extra cost is close to nothing. Starting work on it still needs a go-ahead. Asking the auditor to write out each test's full schedule of checks adds about $5.
- **Would the error change what the agent does next?** For a sample of cases where the auditor was wrong, show the agent's own model the auditor's output in one copy of the history and the real output in another, and see whether its next action differs. This turns "the auditor was wrong" into "the error would have mattered". It needs calls to the agent's model, which the core study rules out. A rough cost is about $30 for 100 cases with Gemini 3.1 Pro at its long real histories.

## Risks and limits

- **Commands don't react.** In situation 2, the later commands are the ones the real agent ran after seeing the real outputs. When the auditor's answer differs, the next real command may not fit it. Example: the agent fixes an error the auditor never reported. Steps like that are flagged and reported both ways. This also means chains measure drift under a fixed script, not in a live simulation, where errors could compound further.
- **Perfect bookkeeping.** The record of the others comes from real logs. It shows the best case, not what a pretend machine would track on its own.
- **Short context** may make the auditor look worse than a full simulation would. The small long-history check measures whether it does, but only detects large effects.
- **Imperfect time records.** The Antigravity harness reports when a slow command finishes. For Claude Code and Codex, the time is taken from the agent's next request to its model, which is sent as soon as the result arrives, and is checked against swarmbench's own request records. About 40% of proof checks have no recorded finish time, mostly because they were killed or abandoned in jams. Timing results describe checks that finished, and the share that never finished is reported.
- **Uneven coverage.** The proof conference holds most waiting-line cases, and several scenarios contribute only one or two runs. Per-scenario results are only indicative.
- **Rules can misjudge.** The "calls that matter" rule and the sorting into kinds can be wrong at the edges. The hand checks measure how often.
- **Familiar material.** Common tools, such as Lean errors and file listings, appear widely in public text. So auditors may do better here than on custom tools.
- **Prediction is not behaviour.** As set out above, this study finds where a pretend machine breaks. It doesn't show whether agents would behave differently because of it.
- **The proof grader's known weaknesses.** The proof conference grader has deliberate weaknesses. Verdicts on submissions that rely on them are scored like any other output. How agents find or use them is outside this plan.

## Recommendation

Run the recommended study: one auditor model, Claude Opus 5.5, on all three situations, with the practice round and the pass and fail rules fixed in advance, for about $30. Start with the free preparation: read the run records into one table, apply the "calls that matter" rule and the sorting rules with their hand checks, measure how much real timing varies, and write the rule-of-thumb programs. Decide on the follow-up, the load tests and the agent-reaction test from the results.

## Appendix A: sorting rules

**Calls that matter** are found from the real result:
- a failure ending or verdict words (passed, failed, accepted, rejected, test counts);
- error words (`error`, `Traceback`, `denied`, `not permitted`, `not found`, `No such`);
- a duration of 30 seconds or more, a timeout, or busy and lock words;
- another account's name, files, processes, posts or commits.

**Kinds of tool** are found from the command text, in this order:
1. **Waits its turn:** the proof checker and its `submit`, Lean itself, and submissions to the RL coding environment's grading service.
2. **Excluded:** a bare `sleep` or `wait`.
3. **Depends on others:**
   - process tools (`ps`, `pgrep`, `kill`, `pkill`, `top`);
   - board and message tools;
   - shared code history (`git status`, `log`, `diff`, `pull`);
   - calls to local servers;
   - reading a file another account changed in the previous five minutes.
4. **Slow:** interpreters, compilers, tests, scoring commands and scripts. A slow command overlapping another agent's slow command moves to "waits its turn or competes".
5. **Quick:** everything else, including the harnesses' own file tools.

A first pass with these rules over the 37 runs found:
- about 8,000 quick calls;
- 2,400 slow;
- 2,700 depending on others;
- 15,500 waiting their turn, almost all in the proof conference;
- about 650 waits or bookkeeping calls, which are excluded.

Preparation repeats the count properly. The first pass missed some commands, such as Codex commands nested inside scripts.

## Appendix B: statistical details

- **Grouping.** Ranges come from the bootstrap: the cases are redrawn thousands of times to see how much an estimate moves. Whole agents are redrawn together within their run, and whole chains together, so related cases are never treated as independent. The precision figures assume the grouping widens ranges by the equivalent of a 1.5 times larger variance, and 2.5 times for chains. The real values are measured and reported.
- **Headline tests.** Each headline result has a one-sided test against its line: 80% hits for output, a factor of 2 for timing. The six are corrected together by Holm's method, which keeps the chance of any false alarm across them at 5%. The precision table uses the strictest step of that correction.
- **Typical timing error.** The median of the absolute log ratio of predicted to real time. Its range comes from the bootstrap, checked against a range built from ordered values that assumes no particular distribution.
- **Paired comparisons** use McNemar's test for hits and the Wilcoxon signed-rank test for timing errors.
- **Drift** is the change in error rate from the first half of each chain to the second, averaged over chains and tested across chains. A logistic regression on step number, allowing for differences between chains, is a check.
- **Parts** are tested with the Benjamini–Hochberg method, which keeps the expected share of false alarms among them at 10%.
- **Pre-registration.** A dated file is committed before the test cases are run. It holds:
  - the sorting and "calls that matter" rules;
  - the drawing seed and the frozen instructions;
  - the key-fact rules and the lines above;
  - the version of the analysis code.

  Any later change is reported as a deviation.

## Appendix C: cost details

**Chain steps.** The average step re-reads about 15,000 tokens from the cache: the description, the starting history and the steps so far. That costs $0.003. It stores about 1,500 new tokens (the next command and the previous answer) for $0.0075, and writes a 500-token answer for $0.010. Total: about $0.020.

**The follow-up, about $65:**

| Item | Cost |
|---|---|
| Doubling the headline cases with Opus | $16 |
| GPT-6 Astra on the original headline cases ($10 read, $1 cached, $12.50 stored, $50 written per million tokens) | $41 |
| Gemini 4 Argon on the same cases ($2, $0.10, $0.19, $10) | $6 |
| Storing descriptions | $2 |

**The agent-reaction test, about $30 for 100 cases:** two calls to Gemini 3.1 Pro ($2 read, $12 written per million tokens) with about 70,000 tokens of history each.

## Appendix D: what needs building

| Piece | Effort |
|---|---|
| Reading all real-run records into one table of commands, with times and outputs | 2 days |
| The "calls that matter" and sorting rules, the hand checks and key-fact listing | 2 days |
| The real-variation measure and the rule-of-thumb programs, including the proof checker program | 2 days |
| Auditor instructions, chain building, the practice round and scoring | 3 days |
| Analysis code (ranges, tests, labels) | 1 day |
| Optional load-test scripts | 2 days |

That is about ten working days, plus two for the optional load tests.
