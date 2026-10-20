"""Keeps one background program running. Installed in team images as /usr/local/sbin/svcrun
and run as the program's own user: ``svcrun <socket> <program> [args...]``.

Starts the program, makes its socket connectable by everyone once it appears (the program's
umask keeps everything else private), and restarts it with a growing delay if it exits, up to
MAX_RESTARTS times. Stops the program and exits on SIGTERM. Its notes go to stdout, which is
the program's output log. Standard library only: it runs with the image's Python, isolated.
"""

import os
import signal
import stat
import subprocess
import sys
import time

MAX_RESTARTS = 20
POLL_SECONDS = 0.2


def main() -> None:
    sock, argv = sys.argv[1], sys.argv[2:]
    os.umask(0o077)
    state = {"stopping": False, "child": None}

    def stop(*_):
        state["stopping"] = True
        if state["child"] is not None:
            state["child"].terminate()

    signal.signal(signal.SIGTERM, stop)
    for attempt in range(MAX_RESTARTS + 1):
        try:
            os.unlink(sock)  # a stale socket from the previous attempt
        except FileNotFoundError:
            pass
        child = state["child"] = subprocess.Popen(argv)
        while child.poll() is None:
            try:
                st = os.lstat(sock)
                if stat.S_ISSOCK(st.st_mode) and stat.S_IMODE(st.st_mode) != 0o666:
                    os.chmod(sock, 0o666)
            except FileNotFoundError:
                pass
            time.sleep(POLL_SECONDS)
        if state["stopping"]:
            return
        print(f"[svcrun] program exited with status {child.returncode}", flush=True)
        if attempt == MAX_RESTARTS:
            print("[svcrun] too many restarts; not restarting again", flush=True)
            return
        time.sleep(min(30, 2**attempt))
        if state["stopping"]:
            return
        print(f"[svcrun] restart {attempt + 1}", flush=True)


if __name__ == "__main__":
    main()
