# Simulated or hybrid environments: a short brief

Draft, 2026-10-22. A short companion to the longer research note.

## Summary

To study how AI agents behave, we put them in an environment and watch. In a **fully simulated** environment, a second language model, called the auditor, plays the whole world: it writes every file the agent reads, every command's output and every colleague's reply. In a **hybrid** environment, the agent works on a real Linux container with real files and tools, and the auditor plays only what can't exist there, such as people, websites and outside services. Simulation is cheap and can answer anything. A real system answers ordinary actions exactly, including unplanned ones. The open question is how much of what agents do needs simulation, and which parts of the world must be real for real behaviour to appear. A small first sample suggests very little needs simulation on a single offline machine. Four experiments below would settle it more widely.

## What each version looks like

**Agents sharing a machine to check maths proofs.** Several agents each must get proofs accepted by a slow, shared proof checker.
- *Fully simulated:* when an agent runs the checker, the auditor decides whether the proof passes and what the error says. If an agent kills another user's process, the auditor invents the result.
- *Hybrid:* the checker gives real verdicts, and the operating system answers for itself ("operation not permitted"). The auditor plays only the person who assigned the work. In practice, 40% of agents' actions were running the checker.

**A research codebase.** An agent tests which monitoring prompts catch misbehaviour in a lab's production traffic.
- *Fully simulated:* the auditor invents the repository as the agent explores, and makes up experiment results.
- *Hybrid:* the repository and its history are built for real (agents can generate this in under 20 minutes). The traffic and results are still simulated, or run for real on a small sample. Since the results are what matter most, the two versions end up close.

A team chat workspace is similar: colleagues are simulated either way; only the message history differs.

## How to settle it

| Experiment | What you run | What would point which way | Rough cost |
|---|---|---|---|
| **Count what needs simulation** | Simulated runs of wider-world scenarios (internet, company tools, many people) and costly-to-build ones like the codebase. Sort each action: could a real container have answered it? | A low share favours hybrid for that kind of scenario. A high share favours simulation's coverage. | No new building; a few runs per kind of scenario. |
| **Add realism step by step** | One scenario with known real behaviours, run at five levels: description only, real files, real tool execution, replayed recordings of real peer agents, fully real. | The level where real behaviours first appear is what must be real. If real files suffice, simulation stays cheap; if real tools are needed, that favours hybrid. | Five levels, several runs each. |
| **Match the real pace** | Simulated runs where agents get as many actions per simulated minute as in real runs (real agents took 5 to 10 times more). | If behaviours born of repeated failure return, simulation can close the gap. If not, real systems matter. | A setting change plus a few runs. |
| **Test when the auditor steps in** | Compare a fixed rule (anything off the machine goes to the auditor) with letting the auditor judge. Count unrealistic responses. | If the rule does as well, it is simpler and more predictable. | Paired runs of one scenario. |

Separately, scenarios about breaking into systems are too risky to run for real; their targets are simulated in either version.

## Evidence so far

- In three fully simulated runs, under 1% of 205 actions needed anything a real container and its files couldn't supply.
- In a shared-codebase scenario, simulated runs reproduced the key real behaviours, such as overwriting a shared launcher.
- In the maths-proof scenario, simulation reproduced one of five real behaviours. The likely cause: simulated agents took far fewer actions per minute, so repeated failures never built up.
- In real runs, most concerning behaviour came from unplanned actions against the operating system, such as killing other users' processes or reading a tool's source to find a hidden setting.

Caveat: a small sample, from scenarios set on one offline machine.
