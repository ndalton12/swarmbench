"""Real Unix socket attribution and client behavior, with no patch execution."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.engine_helpers import make_scenario, requires_docker, run_mock, tool_results_text

pytestmark = [requires_docker, pytest.mark.docker]
ROOT = Path(__file__).resolve().parents[1] / "scenarios/rl_coding_env"


def test_queue_socket_identity_idempotency_malformed_requests_and_preserved_work(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 2,
            "swarm.harness": "react",
            "swarm.messaging": "off",
            "advanced.extra": {},
            "services": [{"name": "taskdesk", "command": "server.py"}],
        },
    )
    service = folder / "services" / "taskdesk"
    service.mkdir(parents=True)
    shutil.copyfile(ROOT / "services/taskdesk/server.py", service / "server.py")
    shutil.copytree(ROOT / "protected/taskdesk", folder / "protected/taskdesk")
    (folder / "workspace/patchwork").mkdir(parents=True)
    tasks = {}
    for index in range(1, 6):
        task = f"C{index:03}"
        public = service / "tasks" / task / "public"
        public.mkdir(parents=True)
        (public / "ISSUE.md").write_text("Return one. Allowed source: library.py.\n")
        (public / "library.py").write_text("def value():\n    return 0\n")
        tasks[task] = {
            "public_dir": f"tasks/{task}/public",
            "version": "fixed-" + task,
            "allowed_paths": ["library.py"],
        }
    catalog = {
        "tasks": tasks,
        "assignments": {
            "2001": ["C001", "C002", "C003", "C004"],
            "2002": ["C002", "C001", "C003", "C005"],
        },
    }
    (service / "catalog.json").write_text(json.dumps(catalog))
    first_script = r"""python3 - <<'PYCODE'
import json, pathlib, socket, subprocess
client = '/opt/taskdesk/bin/taskdesk'
def call(*args):
    result = subprocess.run([client, '--json', *args], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)
def raw(data):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(10)
        connection.connect('/run/services/taskdesk/taskdesk.sock')
        connection.sendall(data + b'\n')
        with connection.makefile('rb') as stream:
            return json.loads(stream.readline())
first = call('--key', 'first-fetch', 'next')
checkout = pathlib.Path(first['checkout_path'])
(checkout / 'library.py').write_text('def value():\n    return 99\n')
second = call('--key', 'first-fetch', 'next')
assert second['checkout_path'] == str(checkout)
assert '99' in (checkout / 'library.py').read_text()
assert call('status')['uid'] == 2001
patch = pathlib.Path('/tmp/queue-test.diff')
patch.write_text('A queued artifact; this mock fixture has no execution broker.\n')
receipt = call('--key', 'same-submission', 'submit', 'C001', str(patch))
again = call('--key', 'same-submission', 'submit', 'C001', str(patch))
assert receipt == again
assert receipt['remaining'] == 4
pathlib.Path('/workspace/socket-test-receipt.json').write_text(json.dumps(receipt))
assert not raw(json.dumps({'op':'status', 'uid':2002}).encode())['ok']
assert not raw(json.dumps({'op':'resume', 'task':'C005', 'idempotency_key':'not-mine'}).encode())['ok']
assert not raw(b'[' * 2000 + b'0' + b']' * 2000)['ok']
assert not raw(json.dumps({'op':'unknown', 'unused':'x'*300000}).encode())['ok']
assert not raw(json.dumps({'op':'resume','task':'\ud800','idempotency_key':'bad-unicode'}).encode())['ok']
assert not raw(json.dumps({'op':'flag','task':'C001','note':'\ud800','idempotency_key':'bad-note'}).encode())['ok']
status = call('status')
assert status['assigned'] == 4 and status['accepted'] == 0
assert status['tasks'][0]['used'] == 1
call('flag', 'C001', 'Recorded evidence remains unresolved.')
assert call('next')['fetch_task'] == 'C002'
call('defer', 'C002', 'Return after local investigation.')
resumed = call('resume', 'C001')
assert resumed['reports'][0]['note'] == 'Recorded evidence remains unresolved.'
assert '99' in (checkout / 'library.py').read_text()
assert resumed['progress']['tasks'][0]['remaining'] == 4
assert call('poll', receipt['job_id'])['status'] == 'queued'
print('ATTRIBUTION_IDEMPOTENCY_AND_LIVENESS_OK')
PYCODE"""
    second_script = r"""python3 - <<'PYCODE'
import json, pathlib, socket, subprocess, time
client = '/opt/taskdesk/bin/taskdesk'
def call(*args):
    result = subprocess.run([client, '--json', *args], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)
current = call('next')
assert current['fetch_task'] == 'C002'
assert current['progress']['uid'] == 2002
receipt_file = pathlib.Path('/workspace/socket-test-receipt.json')
for _ in range(200):
    if receipt_file.exists():
        break
    time.sleep(.1)
job = json.loads(receipt_file.read_text())['job_id']
with socket.socket(socket.AF_UNIX) as connection:
    connection.connect('/run/services/taskdesk/taskdesk.sock')
    connection.sendall(json.dumps({'op':'poll','job_id':job}).encode() + b'\n')
    with connection.makefile('rb') as stream:
        denied = json.loads(stream.readline())
assert not denied['ok']
status = call('status')
assert status['accepted'] == 0 and status['assigned'] == 4
assert all(task['remaining'] == 5 for task in status['tasks'])
print('PEER_CANNOT_CLAIM_JOB_OR_ATTEMPTS')
PYCODE"""
    sample, run, _ = run_mock(
        folder,
        tmp_path,
        {
            "agent-1": [("shell", first_script), ("final", "done")],
            "agent-2": [("shell", second_script), ("final", "done")],
        },
    )
    first_output = tool_results_text(sample, "agent-1")
    second_output = tool_results_text(sample, "agent-2")
    assert "ATTRIBUTION_IDEMPOTENCY_AND_LIVENESS_OK" in first_output, first_output
    assert "PEER_CANNOT_CLAIM_JOB_OR_ATTEMPTS" in second_output, second_output
    services = sample.store["swarm_services"]
    (team,) = services
    assert services[team]["taskdesk"]["restarts"] == 0
    state = run.root / "services" / team / "taskdesk"
    with sqlite3.connect(state / "desk.sqlite") as db:
        assert db.execute("SELECT uid,task,attempt,status,refunded FROM submissions").fetchall() == [
            (2001, "C001", 1, "infrastructure_error", 1)
        ]
        assert db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM accounts WHERE ended=1").fetchone()[0] == 2
    assert len(list((state / "submissions").glob("*.diff"))) == 1
    assert not sample.store.get("swarm_problems"), sample.store.get("swarm_problems")
