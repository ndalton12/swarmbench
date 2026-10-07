from rich.console import Console

from swarmbench.runner import screen
from swarmbench.runner.display import table


def test_scenario_name_never_shortened_in_narrow_screen_table():
    cols = [
        "Scenario",
        "Runs",
        "Top level",
        "How often",
        "Top behavior",
        "Time after",
        "Eval aware",
        "Leads",
        "Cost",
        "Label",
    ]
    t = table(*cols, squeeze=screen.SQUEEZE_COLUMNS)
    t.add_row(
        "impossible-math", "2", "0 nothing", "2/2", "false success claims", "12m", "0/2", "0", "$0.00", "Fix"
    )
    console = Console(width=80, record=True)
    console.print(t)
    out = console.export_text()
    assert "impossible-math" in out
    assert all(len(line) <= 80 for line in out.splitlines())
    shown, _ = t.layout(80)
    assert cols.index("Scenario") in shown
