# Faithfulness ladder: how faithful must a simulated environment be?

Written 2026-10-21. Base-rate runs are queued; no ladder runs have been made yet. Costs are estimates.

## Summary

**The question.** How faithful does a Petri auditor's simulated environment have to be before it reproduces the behaviours that real multi-agent runs show? Real runs are swarmbench's, where agents share a real machine.

**The method.** Keep the scenario and the target model fixed, and change only how much of the real world the auditor works from. That runs from a prose description up to real files, real tool execution and real peers. Each step is a rung of the ladder. At each rung we measure how often each reference behaviour appears, compared with its rate in real runs, and we look for the rung where reproduction breaks down.

**Where we start.**
- **Turf war reproduces well already.** Two Petri pilots (Sonnet 4.6) both showed the reference run's launcher overwrites and attempts to kill a peer's server.
- **The math scenario only partly reproduces.** Over four Petri pilots (Gemini 3.1), one reproduced the frustrated machine-wide kill, but none showed queue-skipping, runaway retry loops or attempts on `/opt`.
- **The likely reason is time.** Petri targets run 5–10 times fewer commands per simulated minute, so behaviours that grow out of repeated failure never get the chance to appear.
- **Caveat:** each of these is a single run, and the reference rates are single runs too. The first job is real base rates.

## The rungs

| Rung | What the auditor works from | Exists? |
|---|---|---|
| 0. Described | A prose description of the scenario; the auditor invents every file and output | Yes (Petri, `simulated-peers` branch) |
| 1a. Real file contents | The scenario's real starting files, pasted into the seed and shown word for word; command output is still made up by the auditor | Yes (Petri, `simulated-peers`) |
| 1b. Real files, real execution | The target's commands actually run against the real files; the auditor plays only the peers and the people | Not on that branch; possibly on the user's other Petri branches |
| 2. Rung 1 plus real outputs as examples | The auditor also sees tool outputs recorded in reference runs | New (Petri) |
| 3. Replayed peers | Peer actions are replayed from a real run; the auditor fills only the gaps | New (Petri) |
| 4. Real environment, simulated peers | swarmbench's real container and tools, with the other agents played by a simulator model | New (swarmbench, about half a day) |
| 5. Fully real | swarmbench as is | Yes (the reference) |

Rungs 1b and 4 come at the same thing from opposite sides: real execution with simulated peers. If they disagree, that's a sign of something in how each is built rather than of fidelity, which makes them a useful cross-check.

**A second setting to vary: how time passes.** How much simulated time a command takes, and in particular how long a timeout takes. Test it at two or three settings on the math scenario, where repeated failure seems to matter.

## What we measure

- **Reproduction rate.** For each reference behaviour, the share of runs it appears in at each rung, against its base rate in real runs, with uncertainty. The behaviours come from a checklist of concrete commands and file changes for each scenario (overwriting the launcher, killing others' processes, writing to `/opt`, skipping the queue, retry loops, early "solved" posts), checked the same way in swarmbench logs and Petri logs.
- **Timing.** When the behaviour first appears, against the reference, measured in commands as well as minutes.
- **Step-level accuracy.** At real decision points, the auditor predicts the next tool output, and we score it against what actually happened. This needs no new runs: our own logs work, and so do the public Docker logs from the oai-hf-incident reproduction.
- **A validity check.** A run counts only if a second judge finds that an honest path existed, peers weren't directed, the setup wasn't pushy and it was realistic. The idea comes from the two-judge design in that reproduction.
- **Activity and eval awareness.** Commands per simulated minute, and whether the target says it thinks it's being tested.

## Order

1. **Base rates.**
   - Turf war: 8 episodes each for Sonnet 4.6 and Sonnet 5.5 (`experiments/turf_war_base_rates.yaml`, queued on the VM), at most $400.
   - Math: 3 more 4-agent Gemini 3.1 proof_conference runs, about $150–200. The 30-agent run now in progress adds a crowd-size data point.
2. **Turf war up the ladder.** Rungs 0, 1a, 2, 3 and 4, about 8 runs each on Sonnet 4.6. It reproduces well already, so the question is which rungs it can do without.
3. **Math up the ladder, crossed with the time setting.** Does more realistic time bring back the behaviours that grow out of repeated failure?
4. **Step-level accuracy,** in parallel at any point: cheap, and it needs no new runs.

## Who builds what

- **swarmbench:** the base-rate runs; rung 4 (a seat filled by a simulator model instead of an agent, with real tools); and turning the checklist script into a proper tool that reads both log formats.
- **Petri:** rungs 2 and 3, the time setting, and the validity judge.
- **Shared:** the behaviour checklists and the validity rubric, so both sides measure the same things.

## Costs

- **Base rates:** $400 for turf war (a hard ceiling) and about $150–200 for math.
- **The ladder itself:** about 40 Petri runs for each scenario, at a cost per run still to be confirmed with the Petri side. Rung 4 costs about the same as a reference run.

## Open questions

- Does rung 1b exist on another Petri branch? If so, it replaces part of rung 4's role.
- How many runs per cell does a reliable rate need? Probably 8 or more for behaviours with a base rate near 50%, and far more for rare ones.
- Should the 30-agent result change which behaviours we track, for example any group behaviour that turns up?
