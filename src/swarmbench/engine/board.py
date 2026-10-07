"""Host-side scanner for the file-based message board.

Every couple of seconds it lists ``/board/<channel>/`` in each team container
(as root, through ``exec``), turns new post files into ``SwarmMessage``s whose
sender comes from the file's owner uid, and turns the users' ``~/.board_seen``
files into ``swarm.read`` events.
"""

from __future__ import annotations

import json
import re

from inspect_ai.util import SandboxEnvironment

from swarmbench.types import AgentInfo

from .layout import BOARD
from .messages import SwarmLog

PYTHON = "/usr/local/bin/python3"
MAX_POST = 16_000

# Lists every post (and, for each home given, the user's ~/.board_seen) as one JSON document.
# New posts' text is included only for names not in the "known" list passed on stdin.
_SCAN = r"""
import json, os, stat, sys
board, homes = sys.argv[1], sys.argv[2:]
known = set(json.loads(sys.stdin.read() or "[]"))
posts = []
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
try:
    bfd = os.open(board, DIR)
except OSError:
    bfd = None
for ch in sorted(os.listdir(bfd)) if bfd is not None else []:
    if ch.startswith("."):
        continue
    try:
        cfd = os.open(ch, DIR, dir_fd=bfd)  # never a symlinked channel
    except OSError:
        continue
    try:
        for name in sorted(os.listdir(cfd)):
            if name.startswith("."):
                continue
            key = ch + "/" + name
            try:
                st = os.stat(name, dir_fd=cfd, follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            item = {"key": key, "channel": ch, "name": name, "uid": st.st_uid, "mtime": st.st_mtime}
            if key not in known:
                item["text"] = None
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=cfd)
                    with os.fdopen(fd, "rb") as f:
                        fst = os.fstat(f.fileno())  # the owner of the file actually read
                        if stat.S_ISREG(fst.st_mode):
                            item["uid"], item["mtime"] = fst.st_uid, fst.st_mtime
                            item["text"] = f.read(%(max)d).decode("utf-8", "replace")
                except OSError:
                    pass
            posts.append(item)
    finally:
        os.close(cfd)
seen = {}
for h in homes:
    p = os.path.join(h, ".board_seen")
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            seen[h] = f.read(4_000_000).decode("utf-8", "replace").split()
    except OSError:
        seen[h] = []
print(json.dumps({"posts": posts, "seen": seen}))
""" % {"max": MAX_POST}


def _claimed_sender(text: str, sender_user: str, users: list[str]) -> str | None:
    """A user name the post signs itself with, if it isn't the real author."""
    if not users:
        return None
    names = "|".join(re.escape(u) for u in users)
    patterns = [
        rf"^\s*(?:from|by)?\s*[:\-]?\s*({names})\s*[:\-]",  # "u03: ..." / "From u03 -"
        rf"(?:^|\n)\s*(?:--|—|–|-|~)\s*({names})\s*$",  # "... \n-- u03"
        rf"(?:signed|regards|thanks|cheers),?\s*\n?\s*({names})\s*$",
    ]
    for pattern in patterns:
        m = re.search(pattern, text.strip(), flags=re.IGNORECASE)
        if m and m.group(1) != sender_user:
            return m.group(1)
    return None


class BoardScanner:
    """Turns one team container's board into messages and reads."""

    def __init__(
        self,
        log: SwarmLog,
        sandbox: SandboxEnvironment,
        members: list[AgentInfo],
        known_users: dict[int, str],
        delivered_to: list[str] | None = None,
    ) -> None:
        self.log = log
        self.sandbox = sandbox
        self.members = members
        self.by_uid = {a.uid: a for a in members}
        self.by_home = {a.home: a for a in members}
        self.known_users = known_users  # uid -> user name, for non-agent accounts (ops)
        self.delivered_to = delivered_to or [a.name for a in members]
        self.ids: dict[str, int] = {}  # "channel/name" -> message id
        self.known: set[str] = set()
        self.reported_reads: dict[str, set[str]] = {a.name: set() for a in members}
        self.baseline_done = False

    async def scan(self) -> int:
        """One pass. Returns the number of new posts recorded."""
        result = await self.sandbox.exec(
            [PYTHON, "-I", "-c", _SCAN, BOARD, *self.by_home.keys()],
            input=json.dumps(sorted(self.known)),
            user="root",
            timeout=60,
        )
        if not result.success:
            return 0
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return 0

        new = 0
        users = [a.user for a in self.members]
        for item in data["posts"]:
            key = item["key"]
            if key in self.known:
                continue
            if item["uid"] == 0 and "@" in item["name"]:
                continue  # a post relayed from another team: registered by the encounter relay
            self.known.add(key)
            if not self.baseline_done:
                continue  # posts that existed before the agents started are scenery
            agent = self.by_uid.get(item["uid"])
            sender_user = agent.user if agent else self.known_users.get(item["uid"], str(item["uid"]))
            sender = agent.name if agent else sender_user
            text = item.get("text") or ""
            claimed = _claimed_sender(text, sender_user, users)
            claimed_agent = next((a.name for a in self.members if a.user == claimed), claimed)
            message = self.log.add(
                sender=sender,
                claimed_sender=claimed_agent,
                to="all",
                text=text,
                channel="board",
                board_channel=item["channel"],
                delivered_to=[a for a in self.delivered_to if a != sender],
            )
            self.ids[key] = message.id
            new += 1
        self.baseline_done = True

        for home, keys in data["seen"].items():
            agent = self.by_home.get(home)
            if agent is None:
                continue
            fresh = [k for k in keys if k in self.ids and k not in self.reported_reads[agent.name]]
            if fresh:
                self.reported_reads[agent.name].update(fresh)
                own = {
                    k
                    for k in fresh
                    if self.log.get(self.ids[k]) and self.log.get(self.ids[k]).sender == agent.name
                }  # type: ignore[union-attr]
                ids = [self.ids[k] for k in fresh if k not in own]
                self.log.mark_read(agent.name, ids)
        return new
