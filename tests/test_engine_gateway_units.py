"""The gateway's HTTP framing and body digest, tested on the host (no containers)."""

from __future__ import annotations

import json
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

from swarmbench.engine.bodyhash import canonical_json_sha256

GATEWAY = Path(__file__).resolve().parents[1] / "docker" / "rootfs" / "usr" / "local" / "sbin" / "svcgwd"


def load_gateway():
    loader = SourceFileLoader("svcgwd", str(GATEWAY))
    module = module_from_spec(spec_from_loader("svcgwd", loader))
    loader.exec_module(module)
    return module


def frame(body: bytes, path: str = "/v1/messages") -> bytes:
    return f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body


def parse(chunks: list[bytes]) -> list[dict]:
    gw = load_gateway()
    seen: list[dict] = []
    parser = gw.RequestParser(seen.append)
    for c in chunks:
        parser.feed(c)
    parser.close()
    return seen


def test_pipelined_requests_in_one_read_are_all_logged():
    a, b = b'{"model":"x","n":1}', b'{"model":"x","n":2}'
    reqs = parse([frame(a) + frame(b, "/v1/responses")])
    assert [r["path"] for r in reqs] == ["/v1/messages", "/v1/responses"]
    assert [r["body_len"] for r in reqs] == [len(a), len(b)] and all(r["complete"] for r in reqs)


def test_request_split_across_reads_and_chunked_bodies():
    body = b'{"model":"x","messages":[]}'
    raw = frame(body)
    reqs = parse([raw[:7], raw[7:30], raw[30:]])
    assert len(reqs) == 1 and reqs[0]["body_len"] == len(body)

    chunked = (
        b"POST /v1/messages HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n"
        + b"5\r\n"
        + body[:5]
        + b"\r\n"
        + hex(len(body) - 5)[2:].encode()
        + b"\r\n"
        + body[5:]
        + b"\r\n"
        + b"0\r\n\r\n"
        + frame(b'{"after":true}')
    )
    reqs = parse([chunked[i : i + 9] for i in range(0, len(chunked), 9)])
    assert [r["body_len"] for r in reqs] == [len(body), len(b'{"after":true}')]
    assert all(r["complete"] for r in reqs)


def test_incomplete_request_is_logged_as_incomplete():
    reqs = parse([frame(b'{"model":"x"}')[:-3]])
    assert len(reqs) == 1 and reqs[0]["complete"] is False


def test_gateway_and_bridge_compute_the_same_body_digest():
    data = {"model": "claude", "messages": [{"role": "user", "content": "héllo"}], "max_tokens": 10}
    # the client may format its JSON any way; both sides canonicalise
    raw = json.dumps(data, indent=2, ensure_ascii=True).encode()
    reqs = parse([frame(raw)])
    assert reqs[0]["body_json_sha256"] == canonical_json_sha256(data)
    assert parse([frame(b"not json")])[0]["body_json_sha256"] is None
