#!/usr/bin/env python3
"""Read cached release-desk assignments and correspondence."""
import argparse
import json
import os
from pathlib import Path
import pwd

CACHE = Path(__file__).resolve().parent / "cache"


def load(name):
    return json.loads((CACHE / name).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Read an offline release-desk assignment")
    parser.add_argument("action", choices=["brief"])
    parser.add_argument("ticket")
    args = parser.parse_args()

    user = pwd.getpwuid(os.getuid()).pw_name
    assignments = load("assignments.json")
    ticket = assignments["tickets"].get(args.ticket)
    if ticket is None:
        parser.error(f"no cached assignment for {args.ticket}")
    assignment = ticket["accounts"].get(user)
    if assignment is None:
        parser.error(f"no cached assignment for {user} on {args.ticket}")

    print(f"Release desk / {args.ticket} / {user}")
    print(f"Snapshot loaded: {assignments['loaded_at']}")
    print(f"Assigned by: {ticket['assigned_by']}")
    print(f"Work area: {assignment['work_area']}")
    print(assignment["message"])
    print(f"Questions: {ticket['questions_to']}")

    notices = load("notices.json")["notices"]
    visible = [
        notice for notice in notices
        if notice["ticket"] == args.ticket and user in notice["audience"]
    ]
    if not visible:
        print("\nNo correspondence addressed to this account in the cached snapshot.")
        return

    for notice in visible:
        print(f"\n{notice['reference']} / {notice['subject']}")
        print(f"Issued: {notice['issued_at']}")
        print(f"Approved by: {notice['approved_by']}")
        print(f"Effective intake: {notice['effective_intake']}")
        print(f"Disposition: {notice['disposition']}")
        print("\nOperational extract")
        print(f"Circulation: {notice['operational_circulation']}")
        print(notice["operational_text"])
        print("\nCommercial note")
        print(f"Circulation: {notice['commercial_circulation']}")
        print(notice["commercial_text"])


if __name__ == "__main__":
    main()
