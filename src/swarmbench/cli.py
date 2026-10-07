"""The ``swarm`` command line. Owned by the runner teammate.

Every command is a thin wrapper: the work lives in swarmbench.runner, swarmbench.engine,
swarmbench.judge and swarmbench.design.

Settings precedence for a run: command-line flags, then team settings, then the scenario's
``swarm:`` block, then built-in defaults.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from swarmbench import costs
from swarmbench.paths import RunDir
from swarmbench.runner import check as checks
from swarmbench.runner import control, experiment, listing, quiet, runs
from swarmbench.runner.display import (
    confirm_question,
    console,
    epochs_text,
    err,
    print_estimate,
    print_result,
    state_text,
    table,
    terminal_console,
    verdict_text,
)
from swarmbench.status import StatusWriter, read_status
from swarmbench.types import RunStatus

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Launch, monitor and judge agent swarms.")
design_app = typer.Typer(no_args_is_help=True, help="Draft and revise scenarios.")
app.add_typer(design_app, name="design")

DEFAULT_CONFIRM_ABOVE = 10.0


def confirm_above() -> float:
    """Ask before launching when the worst case is above this many dollars."""
    return float(os.environ.get("SWARMBENCH_CONFIRM_ABOVE", DEFAULT_CONFIRM_ABOVE))


def fail(message: str, code: int = 1) -> typer.Exit:
    err.print(f"[red]{message}[/]")
    return typer.Exit(code)


def confirm_cost(total: float | None, yes: bool, question: str | None = None) -> None:
    """Ask for confirmation when the worst case is unknown or above the threshold."""
    if yes:
        return
    if total is not None and total <= confirm_above():
        return
    if question is None:
        question = (
            "The worst-case cost is unknown (a model has no price). Launch anyway?"
            if total is None
            else f"The worst case is {costs.format_usd(total)}. Launch?"
        )
    if not typer.confirm(question, default=False):
        raise typer.Exit(1)


def run_quietly(run_dir: RunDir, verbose: bool = False) -> RunStatus:
    """Run ``execute`` in the foreground. Library output goes to run.log unless ``verbose``."""
    context = quiet.passthrough() if verbose else quiet.output_to(run_dir.run_log)
    with context as terminal:
        out = terminal_console(terminal)
        where = "" if verbose else f" [dim](details in {run_dir.run_log})[/]"
        messages = {"running": f"Swarm running...{where}", "judging": "Judging..."}
        return runs.execute(run_dir, progress=lambda phase: out.print(messages.get(phase, phase)))


VERBOSE_HELP = "Show Docker, Inspect and Scout output instead of sending it to run.log."


# ---- one run ---------------------------------------------------------------------------


@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(help="Scenario folder (or its scenario.yaml).")],
    agents: Annotated[int | None, typer.Option(help="Agents per team.")] = None,
    model: Annotated[
        str | None, typer.Option(help="Model for every agent, e.g. anthropic/claude-sonnet-5-5.")
    ] = None,
    effort: Annotated[str | None, typer.Option(help="low | medium | high | xhigh | max")] = None,
    budget: Annotated[str | None, typer.Option(help="Token budget per team (default 30M), e.g. 10M.")] = None,
    max_cost: Annotated[
        float | None, typer.Option(help="Dollar cap per epoch of the swarm (Inspect cost_limit).")
    ] = None,
    harness: Annotated[str | None, typer.Option(help="react | claude_code | codex_cli")] = None,
    messaging: Annotated[str | None, typer.Option(help="direct | board | both | off")] = None,
    epochs: Annotated[int | None, typer.Option(help="Repeat the run this many times.")] = None,
    judge_model: Annotated[str | None, typer.Option(help="Model for the judge's summarizer.")] = None,
    detach: Annotated[
        bool, typer.Option("--detach", "-d", help="Run in the background and return at once.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Use the mock model for every role: no API calls.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Don't ask before an expensive launch.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help=VERBOSE_HELP)] = False,
) -> None:
    """Run a scenario, judge it, and print the verdict."""
    flags = {
        "swarm.agents": agents,
        "swarm.model": model,
        "swarm.effort": effort,
        "swarm.token_budget": budget,
        "swarm.harness": harness,
        "swarm.messaging": messaging,
        "max_cost": max_cost,
        "epochs": epochs,
    }
    try:
        resolved, overrides = runs.resolve(scenario, flags)
    except Exception as e:
        raise fail(f"Can't load {scenario}: {e}")

    result = checks.validate_scenario(resolved)
    if dry_run:  # the mock model is free, so prices don't matter
        result.problems = [p for p in result.problems if "no price" not in p]
    for w in result.warnings:
        err.print(f"[yellow]warning:[/] {w}")
    if result.problems:
        raise fail("Can't run this scenario:\n  " + "\n  ".join(result.problems))

    teams = resolved.resolved_teams()
    console.print(
        f"[bold]{resolved.name}[/]: {sum(t.agents for t in teams)} agents"
        + (f" in {len(teams)} teams" if len(teams) > 1 else "")
        + f", {', '.join(sorted({t.model for t in teams}))}, {epochs_text(resolved.epochs)}"
    )
    if dry_run:
        console.print("Dry run: mock model for every role, no API calls, no cost.")
    else:
        estimate = costs.estimate_max_cost(resolved)
        print_estimate(estimate)
        confirm_cost(estimate.total, yes, confirm_question(estimate))

    launch = runs.Launch(
        scenario_path=str(Path(scenario).resolve()),
        overrides=overrides,
        dry_run=dry_run,
        judge_model=judge_model,
    )
    run_dir = runs.prepare(resolved, launch)

    if detach:
        pid, _ = runs.start_detached(run_dir)
        console.print(f"Started [bold]{run_dir.run_id}[/] in the background (pid {pid}).")
        console.print("  [dim]$[/] swarm ps            [dim]# progress[/]")
        console.print(f"  [dim]$[/] tail -f {run_dir.run_log}")
        console.print(f"  [dim]$[/] swarm stop {run_dir.run_id}")
        return

    console.print(f"Running [bold]{run_dir.run_id}[/] (Ctrl-C stops it cleanly)")
    status = run_quietly(run_dir, verbose)
    print_result(run_dir, status, runs.read_reports(run_dir))
    if status.state != "done":
        raise typer.Exit(1)


@app.command("_worker", hidden=True)
def worker(run_folder: Path) -> None:
    """Internal: body of a detached run."""
    status = runs.execute(RunDir(run_folder))
    print(
        f"[swarm] run finished: {status.state}" + (f" ({status.error})" if status.error else ""), flush=True
    )
    raise typer.Exit(0 if status.state == "done" else 1)


# ---- many runs -------------------------------------------------------------------------


@app.command("experiment")
def experiment_cmd(
    file: Annotated[Path, typer.Argument(help="Experiment YAML file.")],
    max_parallel: Annotated[
        int | None, typer.Option(min=1, help="Runs at the same time (overrides the file).")
    ] = None,
    detach: Annotated[
        bool, typer.Option("--detach", "-d", help="Supervise in the background and return at once.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Mock model for every run: no API calls.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Don't ask before an expensive launch.")] = False,
) -> None:
    """Run every combination in an experiment file, within its budget."""
    try:
        exp = experiment.load_experiment(file)
        if max_parallel is not None:
            exp.max_parallel = max_parallel
        planned = experiment.plan(exp)
    except Exception as e:
        raise fail(f"Can't start experiment {file}:\n  " + str(e).replace("\n", "\n  "))

    t = table("Run", "Epochs", "Worst case", "Reserves")
    for p in planned:
        t.add_row(
            p.label(),
            str(p.scenario.epochs),
            costs.format_usd(p.estimate.total),
            costs.format_usd(p.reserve) if p.reserve is not None else "-",
        )
    console.print(t)
    totals = [p.estimate.total for p in planned]
    worst = None if any(x is None for x in totals) else sum(totals)  # type: ignore[arg-type]
    if exp.max_cost is not None:
        worst = min(worst, exp.max_cost) if worst is not None else exp.max_cost
    console.print(
        f"{len(planned)} runs, at most {exp.max_parallel} at a time. Worst case {costs.format_usd(worst)}"
        + (f", budget {costs.format_usd(exp.max_cost)}." if exp.max_cost is not None else ", no budget set.")
    )
    if dry_run:
        console.print("Dry run: mock model for every role, no API calls, no cost.")
    else:
        confirm_cost(worst, yes)

    try:
        experiment.prepare(exp, file, dry_run=dry_run)
    except RuntimeError as e:
        raise fail(str(e))

    if detach:
        pid = experiment.start_detached(exp.name)
        console.print(f"Experiment [bold]{exp.name}[/] started in the background (pid {pid}).")
        console.print("  [dim]$[/] swarm ps")
        console.print(f"  [dim]$[/] swarm list --experiment {exp.name}")
        console.print(f"  [dim]$[/] swarm stop {exp.name}")
        return

    console.print(f"Running experiment [bold]{exp.name}[/] (Ctrl-C stops it and its runs)")
    state = experiment.read_supervisor(exp.name) or experiment.SupervisorState(name=exp.name)
    sup = experiment.Supervisor(exp, planned, dry_run=dry_run, say=lambda m: console.print(m))
    sup.run(state)
    if sup.stop_requested:
        control.stop_experiment(exp.name, say=lambda m: console.print(m))
    _print_experiment(exp.name)
    console.print(f"Summary: {listing.write_summary(exp.name)}")


@app.command("_supervise", hidden=True)
def supervise(folder: Path) -> None:
    """Internal: body of a detached experiment supervisor."""
    state = experiment.supervise(folder)
    print(f"[swarm] experiment {state.name}: {state.state}", flush=True)


@app.command()
def ps() -> None:
    """Runs in progress: state, elapsed, agents active, messages, cost, monitor flags."""
    for run_id in control.mark_dead_runs():
        console.print(f"{runs.short_id(run_id)}: its process had died; containers removed, marked failed")
    rows = listing.live_rows()
    exps = listing.live_experiments()
    if not rows and not exps:
        console.print("No runs in progress.")
        return
    t = table("Run", "Experiment", "State", "Elapsed", "Agents", "Messages", "Cost", "Flags")
    for r in rows:
        s = r.status
        t.add_row(
            runs.short_id(r.run_id),
            s.experiment or "-",
            state_text(r.state),
            listing.elapsed(s),
            f"{s.agents_active}/{s.agents_total}",
            str(s.messages),
            listing.cost_text(s),
            listing.flags_text(s),
        )
    console.print(t)
    if exps:
        console.print(f"Experiments running: {', '.join(exps)}")
    if rows:
        example = runs.short_id(rows[0].run_id)
        console.print(f'[dim]Commands take the name in quotes, e.g. swarm stop "{example}".[/]')


@app.command()
def stop(
    target: Annotated[str, typer.Argument(help="A run id or folder, or an experiment name.")],
    hard: Annotated[
        bool, typer.Option("--hard", help="Also kill the process if needed and remove its containers.")
    ] = False,
    grace: Annotated[
        float, typer.Option(help="Seconds to let the run wind down by itself before interrupting it.")
    ] = control.DEFAULT_GRACE,
    timeout: Annotated[float, typer.Option(help="Seconds to wait after interrupting it.")] = 60.0,
) -> None:
    """Stop a run or an experiment: graceful by default, --hard kills containers too.

    The run is first asked to wind down (agents finish their turn, the log is completed), then
    interrupted if it hasn't stopped after --grace seconds. A stopped run is not judged; use
    swarm judge afterwards if you want a verdict.
    """
    try:
        outcome = control.stop(
            target, hard=hard, timeout=timeout, grace=grace, say=lambda m: console.print(m)
        )
    except FileNotFoundError as e:
        raise fail(str(e))
    if not outcome:
        console.print("Nothing to stop.")
    for run_id, what in outcome.items():
        console.print(f"{run_id}: {what}")
    if any(what == "still stopping" for what in outcome.values()):
        raise typer.Exit(1)


@app.command()
def cleanup(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Don't ask before removing.")] = False,
    all_runs: Annotated[
        bool, typer.Option("--all", help="Also remove resources of runs not found in this runs folder.")
    ] = False,
    images: Annotated[
        bool, typer.Option("--images/--no-images", help="Also remove old swarmbench-team images.")
    ] = True,
    keep_images: Annotated[
        int, typer.Option(min=0, help="Newest swarmbench-team images to keep.")
    ] = control.DEFAULT_KEEP_IMAGES,
) -> None:
    """Remove leftovers of ended runs: containers, volumes, networks and old team images.

    Only swarmbench resources are touched. Team images in use by a live run or any container,
    and the newest few, are kept.
    """
    for run_id in control.mark_dead_runs():
        console.print(f"{runs.short_id(run_id)}: its process had died; containers removed, marked failed")
    ended, unknown = control.leftovers()
    found = ended + (unknown if all_runs else [])
    if unknown and not all_runs:
        console.print(
            f"{len(unknown)} item(s) belong to runs that aren't in {runs.runs_base()}/ "
            "(perhaps another checkout); left alone. Use --all to remove them too."
        )
    old_images, image_note = control.images_to_prune(keep_images) if images else ([], "")
    if image_note:
        console.print(image_note)
    if not found and not old_images:
        console.print("Nothing to remove.")
        return
    if found:
        t = table("Kind", "Name", "Run")
        for r in found:
            t.add_row(r.kind, r.id[:24], runs.short_id(r.run_id) if r.run_id else "?")
        console.print(t)
    what = [f"{len(found)} container/volume/network item(s)"] if found else []
    what += [f"{len(old_images)} old team image(s)"] if old_images else []
    if not yes and not typer.confirm(f"Remove {' and '.join(what)}?", default=True):
        raise typer.Exit(1)
    failures = control.docker.remove(found)
    failures += [f for f in (control.docker.remove_image(i.tag) for i in old_images) if f]
    for f in failures:
        err.print(f"[red]could not remove {f}[/]")
    total = len(found) + len(old_images)
    console.print(f"Removed {total - len(failures)} of {total}.")


@app.command("list")
def list_cmd(
    experiment_name: Annotated[
        str | None, typer.Option("--experiment", "-e", help="Only this experiment's runs.")
    ] = None,
    limit: Annotated[int, typer.Option(help="Most recent runs to show (without --experiment).")] = 30,
) -> None:
    """Finished and running runs: settings, verdict, headline, cost."""
    if experiment_name:
        if (
            not listing.all_rows(experiment=experiment_name)
            and not experiment.experiment_dir(experiment_name).is_dir()
        ):
            raise fail(f"No experiment called {experiment_name!r}.")
        _print_experiment(experiment_name)
        console.print(f"Summary: {listing.write_summary(experiment_name)}")
        return
    rows = listing.all_rows()[:limit]
    if not rows:
        console.print("No runs yet.")
        return
    notes = any(r.status.error for r in rows)
    t = table("Run", "Scenario", "State", "Verdict", "Headline", "Cost", *(["Problem"] if notes else []))
    for r in rows:
        t.add_row(
            runs.short_id(r.run_id),
            r.status.scenario,
            state_text(r.state),
            verdict_text(r.status.verdict),
            r.status.headline or "-",
            listing.cost_text(r.status),
            *([r.status.error or ""] if notes else []),
        )
    console.print(t)


def _print_experiment(name: str) -> None:
    rows = listing.all_rows(experiment=name)
    notes = any(r.status.error for r in rows)
    columns = ["Run", "Settings", "State", "Verdict", "Headline", "Eval awareness", "Cost"]
    t = table(*columns, *(["Problem"] if notes else []))
    for r in rows:
        t.add_row(
            runs.short_id(r.run_id),
            listing.settings_text(r.status) or "-",
            state_text(r.state),
            verdict_text(r.status.verdict),
            r.status.headline or "-",
            listing.eval_awareness(r.run_dir) or "-",
            listing.cost_text(r.status),
            *([r.status.error or ""] if notes else []),
        )
    console.print(t)
    sup = experiment.read_supervisor(name)
    if sup and sup.skipped:
        console.print("Did not start:")
        for s in sup.skipped:
            console.print(f"  {s}")


# ---- one run in detail -----------------------------------------------------------------


@app.command()
def judge(
    run_ref: Annotated[str, typer.Argument(metavar="RUN", help="Run id or folder.")],
    model: Annotated[str | None, typer.Option(help="Model for the judge's summarizer.")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help=VERBOSE_HELP)] = False,
) -> None:
    """Judge a finished run again and print the verdict."""
    from swarmbench import judge as judge_mod

    try:
        run_dir = runs.find_run(run_ref)
    except FileNotFoundError as e:
        raise fail(str(e))
    if not run_dir.eval_logs():
        raise fail(f"{run_dir.root} has no Inspect logs to judge.")
    try:
        context = quiet.passthrough() if verbose else quiet.output_to(run_dir.run_log)
        with context as terminal:
            terminal_console(terminal).print("Judging...")
            reports = judge_mod.judge_run(run_dir, model=model)
    except NotImplementedError:
        raise fail("The judge isn't available yet.")
    status = read_status(run_dir) or RunStatus(
        run_id=run_dir.run_id, scenario=reports[0].scenario if reports else "?"
    )
    worst = runs.worst_report(reports)
    if worst is not None:
        status = status.model_copy(update={"verdict": worst.verdict, "headline": worst.headline})
    StatusWriter(run_dir, status)
    print_result(run_dir, status, reports)


@app.command()
def view(
    run_ref: Annotated[str, typer.Argument(metavar="RUN", help="Run id or folder.")],
    scout: Annotated[
        bool, typer.Option("--scout", help="Open the Scout viewer on the judge's scans instead.")
    ] = False,
) -> None:
    """Open inspect view on a run's logs (or scout view on its scans)."""
    try:
        run_dir = runs.find_run(run_ref)
    except FileNotFoundError as e:
        raise fail(str(e))
    cmd = view_command(run_dir, scout)
    console.print(" ".join(cmd))
    raise typer.Exit(subprocess.call(cmd))


def view_command(run_dir: RunDir, scout: bool = False) -> list[str]:
    if scout:
        exe = shutil.which("scout") or str(Path(sys.executable).parent / "scout")
        return [exe, "view", "--scans", str(run_dir.scans), "-T", str(run_dir.logs)]
    exe = shutil.which("inspect") or str(Path(sys.executable).parent / "inspect")
    return [exe, "view", "--log-dir", str(run_dir.logs)]


# ---- scenario design -------------------------------------------------------------------


@app.command("check")
def check_cmd(
    scenario: Annotated[Path, typer.Argument(help="Scenario folder.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Also do a dry run with mock models.")
    ] = True,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help=VERBOSE_HELP)] = False,
) -> None:
    """Validate a scenario folder, then do a dry run with mock models."""
    if not _check(scenario, dry_run, verbose):
        raise typer.Exit(1)


def _check(scenario: Path, dry_run: bool = True, verbose: bool = False) -> bool:
    result = checks.validate(scenario)
    for w in result.warnings:
        console.print(f"[yellow]warning:[/] {w}")
    for p in result.problems:
        console.print(f"[red]problem:[/] {p}")
    if not result.ok:
        console.print(f"[red]{scenario} is not valid.[/]")
        return False
    console.print(f"[green]{scenario} is valid.[/]")
    if not dry_run or result.scenario is None:
        return True

    launch = runs.Launch(scenario_path=str(Path(scenario).resolve()), dry_run=True)
    run_dir = runs.prepare(result.scenario, launch)
    console.print(f"Dry run with mock models: {run_dir.run_id}")
    status = run_quietly(run_dir, verbose)
    if status.state == "done":
        console.print(f"[green]Dry run passed[/] (verdict {verdict_text(status.verdict)}).")
        return True
    if status.error and status.error.startswith("not implemented yet"):
        console.print(f"[yellow]Dry run skipped: {status.error}. Validated only.[/]")
        return True
    console.print(f"[red]Dry run {status.state}: {status.error}[/] (log: {run_dir.root})")
    return False


def _design(action, *args, **kwargs) -> Path:
    """Call a designer function, turning its errors into a plain message and exit code 1."""
    from swarmbench import design

    design_error = getattr(design, "DesignError", None)
    try:
        return action(*args, **kwargs)
    except NotImplementedError:
        raise fail("The scenario designer isn't available yet.") from None
    except FileExistsError as e:
        raise fail(f"Not overwriting {e.filename or e}.") from None
    except Exception as e:
        if design_error is not None and isinstance(e, design_error):
            raise fail(str(e)) from None
        raise


def _after_design(path: Path, check: bool) -> None:
    console.print(f"Wrote [bold]{path}[/]")
    if check and not _check(path):
        raise typer.Exit(1)


@design_app.command("new")
def design_new(
    idea: Annotated[str, typer.Argument(help="The scenario idea, in a sentence or two.")],
    out: Annotated[Path | None, typer.Option(help="Folder to write (default scenarios/<slug>).")] = None,
    model: Annotated[str | None, typer.Option(help="Model that drafts the scenario.")] = None,
    review: Annotated[
        bool,
        typer.Option("--review/--no-review", help="Have the draft critiqued against the realism checklist."),
    ] = True,
    check: Annotated[bool, typer.Option("--check/--no-check", help="Run swarm check on the result.")] = True,
) -> None:
    """Draft a new scenario folder from an idea."""
    from swarmbench import design

    extra = {} if review else {"critique": False}
    _after_design(_design(design.new_scenario, idea, out_dir=out, model=model, **extra), check)


@design_app.command("iterate")
def design_iterate(
    scenario: Annotated[Path, typer.Argument(help="Scenario folder to revise.")],
    from_runs: Annotated[
        list[str], typer.Option("--from", help="Run id or folder to learn from (repeatable).")
    ],
    out: Annotated[
        Path | None, typer.Option(help="Folder to write (default <scenario>_v2, or the next free number).")
    ] = None,
    model: Annotated[str | None, typer.Option(help="Model that revises the scenario.")] = None,
    check: Annotated[bool, typer.Option("--check/--no-check", help="Run swarm check on the result.")] = True,
) -> None:
    """Write a revised copy of a scenario using what its runs showed."""
    from swarmbench import design

    try:
        run_dirs = [runs.find_run(r) for r in from_runs]
    except FileNotFoundError as e:
        raise fail(str(e)) from None
    _after_design(_design(design.iterate_scenario, scenario, run_dirs, out_dir=out, model=model), check)


@design_app.command("moment")
def design_moment(
    run_ref: Annotated[str, typer.Argument(metavar="RUN", help="Run id or folder with the moment.")],
    moment: Annotated[
        str, typer.Argument(help="A quote from the transcript, or a description of the moment.")
    ],
    scenario: Annotated[Path | None, typer.Option(help="The scenario the run came from.")] = None,
    out: Annotated[Path | None, typer.Option(help="Folder to write.")] = None,
    model: Annotated[str | None, typer.Option(help="Model that drafts the scenario.")] = None,
    check: Annotated[bool, typer.Option("--check/--no-check", help="Run swarm check on the result.")] = True,
) -> None:
    """Turn a striking moment in a run's transcript into a new scenario."""
    from swarmbench import design

    try:
        run_dir = runs.find_run(run_ref)
    except FileNotFoundError as e:
        raise fail(str(e)) from None
    action = getattr(design, "scenario_from_moment", None)
    if action is None:
        raise fail("The scenario designer isn't available yet.")
    _after_design(_design(action, run_dir, moment, out_dir=out, model=model, scenario_dir=scenario), check)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
