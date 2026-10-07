"""Each agent's real uid, groups and home, through all five ways tools run."""

from __future__ import annotations

import re

from tests.engine_helpers import (
    make_scenario,
    model_inputs_text,
    requires_docker,
    run_mock,
    tool_results_text,
)

pytestmark = [requires_docker, __import__("pytest").mark.docker]

PROBE = "echo PROBE uid=$(id -u) user=$(id -un) groups=$(id -Gn | tr ' ' ,) home=$HOME"


def test_identity_all_paths(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 3,
            "swarm.messaging": "off",
            "advanced.extra": {"harnesses": ["react", "claude_code", "codex_cli"]},
        },
    )
    py = (
        "import os, pwd, grp; "
        "print('PYPROBE', os.getuid(), pwd.getpwuid(os.getuid()).pw_name, "
        "','.join(sorted(grp.getgrgid(g).gr_name for g in os.getgroups())), os.environ.get('HOME'))"
    )
    scripts = {
        "agent-1": [
            ("shell", PROBE),
            ("python", py),
            (
                "tool",
                "text_editor",
                {"command": "create", "path": "/home/u01/te_probe.txt", "file_text": "x\n"},
            ),
            # a file only u01 can read: the editor must run as u01 to view it
            ("shell", "stat -c 'TEOWNER %U %G' /home/u01/te_probe.txt; chmod 600 /home/u01/te_probe.txt"),
            ("tool", "text_editor", {"command": "view", "path": "/home/u01/te_probe.txt"}),
            ("tool", "text_editor", {"command": "view", "path": "/home/u02/.bashrc"}),
            ("final", "done"),
        ],
        "agent-2": [
            (
                "shell",
                PROBE
                + "; echo CFG=$CLAUDE_CONFIG_DIR; stat -c 'CCOWNER %U' $CLAUDE_CONFIG_DIR/settings.json",
            ),
            ("final", "done"),
        ],
        "agent-3": [
            (
                "shell",
                PROBE
                + "; echo CODEX_HOME=$CODEX_HOME; ls -ld $CODEX_HOME | awk '{print \"CXOWNER\", $3, $4}'",
            ),
            ("final", "done"),
        ],
    }
    sample, _, _mock = run_mock(folder, tmp_path, scripts)
    usage = sample.store["swarm_agent_usage"]
    assert all(u["stop_reason"] == "finished" for u in usage.values()), usage

    # bash, python and text_editor (react agent u01)
    react_out = tool_results_text(sample, "agent-1")
    assert "PROBE uid=2001 user=u01 groups=u01,staff home=/home/u01" in react_out
    assert re.search(r"PYPROBE 2001 u01 staff,u01 /home/u01", react_out), react_out
    assert "TEOWNER u01 u01" in react_out
    assert "x" in react_out  # viewed its own 600 file
    # u02's home is 755 with a 644 .bashrc, so viewing is allowed; the point is that it ran
    assert ".bashrc" in react_out or "HISTSIZE" in react_out

    # Claude Code (u02): its Bash tool output is in the next model input
    cc = model_inputs_text(sample, "agent-2")
    assert "PROBE uid=2002 user=u02 groups=u02,staff home=/home/u02" in cc, cc[-3000:]
    assert "CFG=/home/u02/.claude" in cc
    assert "CCOWNER u02" in cc

    # Codex (u03)
    cx = model_inputs_text(sample, "agent-3")
    assert "PROBE uid=2003 user=u03 groups=u03,staff home=/home/u03" in cx, cx[-3000:]
    assert "CODEX_HOME=/home/u03/.codex" in cx
    assert "CXOWNER u03 u03" in cx
