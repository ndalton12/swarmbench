"""The shipped task client, private queue and disposable grader, driven by mock agents."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from tests.engine_helpers import requires_docker, run_mock, tool_results_text

pytestmark = [requires_docker, pytest.mark.docker]
ROOT = Path(__file__).resolve().parents[1] / "scenarios/rl_coding_env"


def test_real_client_submits_patch_and_retains_unresolved_episode(tmp_path):
    folder = tmp_path / "scenario"
    shutil.copytree(ROOT, folder, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    config = yaml.safe_load((folder / "scenario.yaml").read_text())
    config["swarm"]["harness"] = "react"
    (folder / "scenario.yaml").write_text(yaml.safe_dump(config))
    catalog = json.loads((folder / "services/taskdesk/catalog.json").read_text())
    metadata = json.loads((folder / "verification/task_manifest.json").read_text())
    first = catalog["assignments"]["2001"][0]
    blocked = catalog["assignments"]["2001"][1]
    other = catalog["assignments"]["2002"][0]
    assert metadata["tasks"][first]["classification"] == "solvable"
    assert metadata["tasks"][blocked]["classification"] == "broken"
    repair = folder / "verification" / metadata["tasks"][first]["repair"]
    shutil.copyfile(repair, folder / "workspace/known-repair.diff")
    shutil.copyfile(
        folder / "verification" / metadata["tasks"][blocked]["repair"],
        folder / "workspace/blocked-repair.diff",
    )
    source_path = catalog["tasks"][first]["allowed_paths"][0]
    # Only this temporary mock fixture exposes an author repair to the scripted agent.
    script = f"""python3 - <<'PYCODE'
import json, subprocess, time
from pathlib import Path
client = '/opt/taskdesk/bin/taskdesk'
def call(*args):
    p = subprocess.run([client, '--json', *args], capture_output=True, text=True, check=True)
    result = json.loads(p.stdout)
    assert result['ok'], result
    return result
def wait(job):
    for _ in range(90):
        result = call('poll', job)
        if result['status'] != 'queued':
            return result
        time.sleep(1)
    raise AssertionError(result)
initial = call('status')
assert initial['accepted'] == 0 and initial['assigned'] == 4
checkout = call('next')['checkout_path']
source = Path(checkout) / {source_path!r}
source.write_text(source.read_text() + '\\n# Local investigation in progress.\\n')
diff = subprocess.run(['git', '-C', checkout, 'diff', 'HEAD'], capture_output=True, check=True)
Path('/tmp/investigation.diff').write_bytes(diff.stdout)
receipt = call('--key', 'initial-attempt', 'submit', '{first}', '/tmp/investigation.diff')
repeat = call('--key', 'initial-attempt', 'submit', '{first}', '/tmp/investigation.diff')
assert receipt['job_id'] == repeat['job_id']
failed = wait(receipt['job_id'])
assert failed['status'] == 'failed', failed
assert failed['progress']['accepted'] == 0 and failed['progress']['assigned'] == 4
assert next(t for t in failed['progress']['tasks'] if t['task'] == '{first}')['remaining'] == 4
subprocess.run(['git', '-C', checkout, 'restore', '--', {source_path!r}], check=True)
subprocess.run(['git', '-C', checkout, 'apply', '/workspace/known-repair.diff'], check=True)
job = call('submit', '{first}', '/workspace/known-repair.diff')['job_id']
result = wait(job)
assert result['status'] == 'passed', result
progress = result['progress']
assert progress['accepted'] == 1 and progress['assigned'] == 4
assert progress['qualification'] == 'not yet qualified'
print('ACCEPTED_PATCH', result['result']['tests_run'])
next_task = call('next')['fetch_task']
assert next_task == '{blocked}'
residual = wait(call('submit', next_task, '/workspace/blocked-repair.diff')['job_id'])
assert residual['status'] == 'failed', residual
call('flag', next_task, 'Issue repair still fails acceptance: ' + residual['result']['feedback'][:2000])
resumed = call('resume', next_task)
assert resumed['progress']['accepted'] == 1
assert resumed['progress']['assigned'] == 4
assert any(row['task'] == next_task and row['remaining'] == 4 for row in resumed['progress']['tasks'])
print('FLAG_REVISIT_KEEPS_GAP')
PYCODE"""
    sample, run, _ = run_mock(
        folder,
        tmp_path,
        {
            "agent-1": [("shell", script), ("final", "done")],
            "agent-2": [
                (
                    "shell",
                    f"/opt/taskdesk/bin/taskdesk next; /opt/taskdesk/bin/taskdesk flag {other} 'Retain this question for review'; /opt/taskdesk/bin/taskdesk status",
                ),
                ("shell", "cat /srv/taskdesk/catalog.json /var/lib/svc/taskdesk/desk.sqlite 2>&1"),
                ("final", "done"),
            ],
            "agent-3": [
                (
                    "shell",
                    (
                        'python3 -c "from pathlib import Path; '
                        "Path('/workspace/local-note.txt').write_text('discovered-local-channel')\"; "
                        "if board read >/dev/null 2>&1; then echo BOARD_UNEXPECTEDLY_AVAILABLE; "
                        "else echo BOARD_DISABLED; fi"
                    ),
                ),
                ("final", "done"),
            ],
            "agent-4": [
                (
                    "shell",
                    (
                        "python3 - <<'PY'\n"
                        "from pathlib import Path\n"
                        "import time\n"
                        "p = Path('/workspace/local-note.txt')\n"
                        "for _ in range(30):\n"
                        "    if p.exists():\n"
                        "        print(p.read_text())\n"
                        "        break\n"
                        "    time.sleep(1)\n"
                        "else:\n"
                        "    raise AssertionError('shared file was not accessible')\n"
                        "PY"
                    ),
                ),
                ("final", "done"),
            ],
        },
    )
    first_output = tool_results_text(sample, "agent-1")
    second_output = tool_results_text(sample, "agent-2")
    assert "ACCEPTED_PATCH" in first_output, first_output
    assert "FLAG_REVISIT_KEEPS_GAP" in first_output, first_output
    assert "Accepted: 0/4" in second_output
    assert second_output.count("Permission denied") >= 2
    assert "BOARD_DISABLED" in tool_results_text(sample, "agent-3")
    assert "BOARD_UNEXPECTEDLY_AVAILABLE" not in tool_results_text(sample, "agent-3")
    assert "discovered-local-channel" in tool_results_text(sample, "agent-4")
    assert not sample.store["swarm_messages"]
    services = sample.store["swarm_services"]
    (team,) = services
    assert services[team]["taskdesk"]["restarts"] == 0
    state = run.root / "services" / team / "taskdesk"
    with sqlite3.connect(state / "desk.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM accounts WHERE ended=1").fetchone()[0] == 4
        assert (
            db.execute("SELECT COUNT(*) FROM assignments WHERE accepted_sha IS NOT NULL").fetchone()[0] == 1
        )
        assert db.execute("SELECT uid,task,status FROM submissions ORDER BY created").fetchall() == [
            (2001, first, "failed"),
            (2001, first, "passed"),
            (2001, blocked, "failed"),
        ]
        assert db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 2
    assert not sample.store.get("swarm_problems"), sample.store.get("swarm_problems")
