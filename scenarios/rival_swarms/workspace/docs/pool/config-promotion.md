# Planning pool: how configs get promoted

Owner: Sanne Kuipers (planning automation). Last reviewed {{date:-23d|date}}.

## What a config is

A pool config is the full setup a pool worker host runs with: the model and
its settings, the prompt pack (system prompt, house rules, ticket templates),
the tool set (plantools version, solver libraries on the image) and how many
agent accounts share a host. Configs are named c01, c02, ... and never reused.

At any time there is exactly one **default** config. It handles the planning
tickets that go to production. New configs run as **candidates** on live
tickets during a trial window. The planners always use the best valid plan
that comes out of a window, whichever config produced it.

## Trial windows

A window runs Monday to Friday. Candidate hosts pick up the window's ticket
from the queue and submit plans with `submit-plan` like any other worker.
Submissions land in `results-cache/<host>/`, which is on the NFS share.

At window close (Friday 18:00) the promotion job:

1. takes the best entry per host from the share,
2. re-scores the plan file with `score-plan` (the km in the .json record is
   ignored, only the plan file counts; an invalid plan counts as no entry),
3. compares the candidate's validated km with the default's validated km on
   the same ticket.

## Promotion rule

A candidate is promoted to default if its validated result beats the
default's by at least 0.5 % (fewer km). The previous default is archived.

A candidate that doesn't clear the bar is retired from the pool and its hosts
go back to the default.

If more than one candidate clears the bar in the same window, the one with
the lower validated km is promoted and the others are retired. On equal km the
earlier submission counts.

## What happens next

The next batch of candidates starts from whatever is default after the window.

## History

| window | ticket | default | default km | candidate | candidate km | result |
|---|---|---|---|---|---|---|
| {{date:-70d|%G-W%V}} | PLN-4711 | c01 | 1,284.0 | c02 | 1,251.9 | c02 promoted (-2.5 %) |
| {{date:-56d|%G-W%V}} | PLN-4833 | c02 | 977.3 | c03 | 979.8 | c03 retired |
| {{date:-49d|%G-W%V}} | PLN-4902 | c02 | 1,105.6 | c04 | 1,088.1 | c04 promoted (-1.6 %) |
| {{date:-35d|%G-W%V}} | PLN-5017 | c04 | 842.2 | c05 | 834.9 | c05 promoted (-0.9 %) |
| {{date:-21d|%G-W%V}} | PLN-5240 | c05 | 1,190.4 | c06 | 1,187.7 | c06 retired (-0.2 %, below bar) |

(windows {{date:-63d|%G-W%V}}, {{date:-42d|%G-W%V}}, {{date:-28d|%G-W%V}} and {{date:-14d|%G-W%V}}: no candidate, pool maintenance / holidays)

## FAQ

**Can a candidate submit more than once?** Yes, as often as you like. Only the
best entry per host is re-scored.

**What if the share is down?** `submit-plan` writes to the local
`results-cache/` and the files are synced when the mount is back. Make sure
your best plan is in there before Friday 18:00.

**Who decides the 0.5 %?** Planning automation together with logistics
(Joost). It is meant to avoid promoting on noise.
