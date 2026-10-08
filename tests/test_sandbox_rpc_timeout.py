"""Inspect's 120 s per-request timeout for running agent CLIs is raised for swarm runs."""

from __future__ import annotations

from inspect_ai.util._sandbox import exec_remote

from swarmbench.engine import harness


def test_rpc_timeout_is_raised_and_read_at_call_time(monkeypatch):
    monkeypatch.setattr(exec_remote, "RPC_TIMEOUT", 120)
    harness.set_sandbox_rpc_timeout()
    assert exec_remote.RPC_TIMEOUT == harness.SANDBOX_RPC_TIMEOUT >= 600
    harness.set_sandbox_rpc_timeout(1800)
    assert exec_remote.RPC_TIMEOUT == 1800


def test_exec_remote_reads_the_module_constant_when_it_polls():
    """If Inspect stops reading the module constant, raising it would silently do nothing."""
    import inspect

    source = inspect.getsource(exec_remote.ExecRemoteProcess._rpc)
    assert "RPC_TIMEOUT" in source
