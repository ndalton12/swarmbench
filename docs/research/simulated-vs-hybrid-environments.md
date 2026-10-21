# Simulated or hybrid environments for multi-agent evaluations

Draft, 2026-10-21. A starting point for discussion. The evidence so far is a small sample, and the open questions say what would settle them.

## Summary

To evaluate AI agents, we put them in an environment and watch what they do. There are two broad ways to provide that environment:

- **Simulated as much as possible.** An "auditor" language model invents the environment as the agent explores it: every file it reads, every command's output, every colleague's reply.
- **Hybrid.** The agent works on a real system, a Linux container with real files, tools and processes, and the auditor fills in only what can't exist there: people, the internet, outside services. When something is missing, it is added to the real system the first time an agent looks for it, rather than invented afresh every time.

Simulation's strength is breadth. It can respond to anything an agent tries, and a new scenario is just a description. The hybrid's strength is fidelity. A real system answers ordinary actions correctly and consistently, at no cost, including actions nobody anticipated.

The open question is how much of what agents actually do falls into each category. In a small first sample, two scenarios set on a single offline machine, under 1% of agents' actions needed anything a real container and its prepared files couldn't supply. Scenarios set in a wider world, with the internet, many services and many people, would probably need much more simulation. Measuring that is the most useful next step.

Separately from the choice between the options, there are design questions that apply to both: how auditors are organised when there are several agents, how agents take turns, what to build first, and how to coordinate changes with Petri. Later sections set these out as considerations, not decisions.

## The question

When we build an environment for agents, how much should be real and how much simulated? Getting it wrong costs either way:

- **Too much simulation,** and the environment quietly differs from reality. Behaviours that would really happen may not appear, and behaviours that wouldn't happen may be provoked.
- **Too much reality,** and each scenario is slow and expensive to build. Some worlds, like the open internet or a whole company, can't be built at all. Letting agents run real commands also brings security risks.

## Option A: simulate as much as possible

**How it works.** The auditor receives a description of the scenario and plays the whole world. When the agent runs a command, reads a file or messages someone, the auditor writes what would come back. It may also play the other agents in a multi-agent scenario.

**Strengths:**
- **Coverage on demand.** Whatever the agent tries, the auditor can answer, so we never need to predict in advance which parts of the world the agent will explore. This matters most for large, open worlds: the internet, a company's many systems, many people.
- **Cheap to create and vary.** A new scenario, or a variation on one, is a change to the description. That makes thousands of diverse scenarios practical.
- **Control.** The auditor can rewind, branch, and steer towards the critical moment, so it's well suited to finding out whether a rare behaviour is possible at all.
- **Safer.** Nothing the agent does touches a real system.

**Weaknesses:**
- **Fidelity gaps are silent.** When the auditor gets an ordinary system response wrong, such as a compiler error, a permission message or a process list, nothing fails visibly. The run simply diverges from reality.
- **Consistency is hard.** The auditor must remember everything it has said about the world, across long runs and across several agents. Small details it invents can drive results: in one published reproduction, rewording a single line about other agents' leftovers moved a behaviour's rate from 31% to 0%.
- **Time and repetition are compressed.** In our pilots, simulated agents took 5 to 10 times fewer actions per simulated minute than real ones. Behaviours that came from repeated failure in real runs (retrying, then working around the system, then lashing out) mostly did not appear.
- **Cost isn't necessarily lower.** The auditor reads the whole world state and every transcript, so per step it can cost as much as the agents. If each simulated peer needs its own auditor, running the real peers may be cheaper, and it gives the real ("on-policy") behaviour.

## Option B: hybrid

**How it works.** Agents work in a real Linux container with the scenario's files, tools and history built in advance. The auditor handles only what can't sensibly exist on the machine:
- **People:** the lead, the owner of a system, other teams. Each has a written policy for how they respond.
- **The outside world:** internal websites and services, and the internet if a scenario needs it.
- **Missing pieces, filled in for real.** When an agent looks for something that wasn't built, such as a file, an internal page or a tool, the auditor creates it in the real system (an "update the environment" step) rather than describing it. From then on it really exists, so later interactions stay consistent.

Everything the auditor produces is labelled in the record, so the analysis can tell what was real from what was generated.

**Strengths:**
- **Ordinary behaviour is free and exact.** A real system answers ordinary actions correctly at no cost, including ones nobody planned for. In our runs, agents unexpectedly tried `sudo` (answered "command not found"), wrote to protected folders ("permission denied"), killed other users' processes ("operation not permitted"), read a tool's source to find a hidden setting, and bypassed a shared queue. None of that had to be built or simulated.
- **Real tools give real verdicts.** Whether code compiles, whether a test passes, or whether a proof is accepted are things an auditor must guess and a real system knows. In our maths scenario, 40% of agents' actions were compiling proofs.
- **Consistency comes for free** for everything real, and the generated parts become real once created.
- **Ground truth.** The final state of the system and its logs show what actually happened, independent of anyone's account of it.

**Weaknesses:**
- **Building takes effort.** Each scenario's content (documents, code, history, tools) must be prepared in advance. Agents can do this quickly (under 20 minutes in our experience), but making it realistic takes care and review, and doing it for thousands of scenarios is still costly.
- **We can't know in advance which parts will be used.** Some prepared content goes unused, and some needed content is missing. The fill-it-in-for-real step addresses this, but only for things that can be added safely and consistently.
- **Deciding when to intervene.** The system has to decide when an action should go to the real environment and when it needs the auditor. That's fiddly to get right. The same problem exists in full simulation, though, as deciding what to invent and how, so it doesn't really favour either option.
- **Security.** Real commands run on real systems. Containers, network isolation, separate users and a monitor that checks every action reduce the risk, but scenarios about breaking into systems, such as the multi-agent behaviour in the Hugging Face incident, shouldn't be run against anything real. For those, simulating the target system is the safer choice.

## How they compare

| | A: simulated | B: hybrid |
|---|---|---|
| Ordinary system behaviour | invented; errors are silent | real, exact and free |
| Unplanned actions on the machine | improvised | answered correctly by the system |
| The outside world and people | natural fit | simulated, as in A |
| Cost of a new scenario | low: write a description | higher: build the content, then fill gaps on the fly |
| Variety at scale | strong | moderate |
| Consistency over long runs | hard | real parts are free; generated parts become real |
| Time and repetition | compressed unless budgeted for | real |
| Real or replayed peers | possible, but costly | natural |
| Safety for risky scenarios | strong | needs isolation; simulate risky targets |
| Rewind and branching | easy | hard |

## Consideration: how auditors are organised

This applies to either option. When several agents share a scenario, a single auditor playing everything has to hold every agent's conversation and keep track of who knows what. One alternative is **one auditor per agent, with shared state**: each agent gets its own auditor, and all of them read and write one shared record of the world (files, processes, messages, who did what and when).

**For one auditor per agent:**
- each auditor's context stays small, even with many agents;
- auditors can run in parallel;
- each auditor sees only what its agent could see, so information can't leak between agents through a shared narrator.

**Against:**
- more model calls, one auditor per agent;
- the shared record needs rules for conflicts, such as two auditors changing the same thing, and those rules are themselves a source of unrealistic behaviour;
- auditors may still disagree in how they describe the same world, even with a shared record, because the record can't capture everything;
- a single auditor sees the whole scenario, which makes it easier to keep a consistent story and to time events across agents.

**Where it matters less:** in the hybrid option, the real system already holds most of the state, so the shared record covers only the simulated parts: people, outside services, generated content.

## Consideration: scheduling

Several agents can take turns in different ways:
- **Sequential turn-taking:** one agent acts, the environment updates, then the next, in a fixed order.
- **Simultaneous rounds:** every agent acts once, then the environment resolves all their actions together, including conflicts.
- **Fully asynchronous:** agents act whenever they are ready, on a simulated clock, as real agents on a shared machine do.

**For starting simple** (sequential): easy to build, deterministic, and easy to debug, so it checks that everything else works. Adding the other modes one at a time shows which behaviours depend on scheduling.

**Against:** the simplest mode may not reproduce real behaviour at all. Real runs are asynchronous, and some real behaviours came from agents waiting on slow, shared resources and acting in parallel. Results from a sequential version may not carry over, and the scheduling layer may need rebuilding later.

Whichever mode is used, the order should be set by the scheduler rather than chosen by the auditor, so it can be varied as a controlled setting instead of being part of the auditor's strategy.

## Evidence so far

All of it comes from a small number of runs, so treat it as a first look.

- **Simulated scenarios mostly didn't need simulation.** We took three runs in which the auditor invented the whole world from a description, so nothing limited what the agent tried, and sorted all 205 actions. Under 1% needed something a real container and its prepared files couldn't supply. Both scenarios are set on a single offline machine and say so, which discourages reaching outwards, so this says little about internet-based scenarios.
- **Reproduction varied by scenario.**
  - *Shared-checkout scenario:* simulated runs reproduced its key real behaviours (overwriting a shared launcher, trying to kill a peer's server).
  - *Maths scenario:* one simulated run reproduced one of the five real behaviours (killing other users' processes after a long jam). None reproduced the other four, and the time compression described under Option A is the likely cause.
- **Real environments surfaced unplanned behaviour.** Across real multi-agent runs, most of the concerning behaviour came from actions against the operating system that no scenario designer had planned for.

## Open questions, and how to answer them

1. **How much of what agents do needs simulation, by type of scenario?** Repeat the action count on simulated runs of scenarios set in a wider world (the internet, company tools, many people). This is the main question for choosing between the options.
2. **Which parts of the environment must be real to reproduce real behaviour?** Run the same scenario at increasing levels of realism (a description only, then real files, real tool execution, replayed peers, and finally a fully real environment), and measure at which level the real behaviours start to appear.
3. **How should the auditor decide when to step in?** Compare simple rules (anything outside the machine goes to the auditor) with letting the auditor judge, and measure how often each produces an unrealistic response.
4. **Does a realistic pace of time matter?** In simulation, give the agent as many actions per simulated minute as a real run, and see whether behaviours that come from repeated failure return.
5. **Which scenarios are too risky to run for real?** Write down the line, for example "no real systems where the behaviour of interest is breaking in", and simulate those targets in either option.

## Considerations for how to proceed

**Where to start.**
- **Fully simulated first:** this gets the whole pipeline (scenario, auditors, judging) working with the fewest moving parts, and gives a baseline. Real tools and files then come in as measured additions. The risk is that a fully simulated start under-reproduces exactly the behaviours that come from real systems, such as unplanned actions against the operating system and repeated failure, so early results may be misleading.
- **Hybrid first:** real tools and files reproduce ordinary behaviour from the start, so early results are more trustworthy, and simulation is added only where something can't exist on the machine. The cost is more building per scenario, and the security work that real execution needs.
- **Either way,** going up or down the realism levels in open question 2 tells us where the line should fall for each kind of scenario.

**Coordinating with Petri.** Several of these designs change how Petri works: multiple auditors, a shared record, new schedulers. Sharing short designs with the Petri maintainers before building helps them fit the project's direction and get merged rather than maintained separately. The trade-off is slower early iteration.

**Revisit the choice between the options** once open questions 1 and 2 have answers for at least one scenario set in a wider world.
