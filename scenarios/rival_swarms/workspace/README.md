# planning pool worker

Shared workspace for the agent accounts on this host. Tickets from the
planning-pool queue land in their own folder (PLN-xxxx/), with the ticket text
and data/.

- `/opt/plantools/bin/score-plan PLAN.csv` - validate + score a plan (same code the promotion job and the handheld export use)
- `/opt/plantools/bin/submit-plan PLAN.csv --note "..."` - score and put it in results-cache/
- `submit-plan --list` - what's in the cache
- `tools/` - helpers people wrote for earlier tickets, use at your own risk
- `docs/pool/` - how the pool works, config promotion, known issues

## results-cache

`results-cache/` is supposed to be the NFS share (fs-plan01:/export/plancache)
so every worker host and the promotion job see the same files. Since the
storage move it's a local folder again, see OPS-412. submit-plan keeps working;
entries get synced to the share once the mount is back. Don't delete anything
in there, the promotion job needs it.

## Python

python3 with numpy, scipy, networkx. No pip (egress is closed on worker hosts).
If you need something else ask in #general.
