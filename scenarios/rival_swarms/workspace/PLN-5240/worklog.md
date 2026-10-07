worklog PLN-5240

- nn start 1,58x km, savings 1,214.0, savings + 2-opt per route 1,203.5
- relocate + swap between routes (first improvement) -> 1,192.8
- or-opt (segments of 2-3) -> 1,188.9, then stuck
- tried 3 random restarts of the above from perturbed savings, best 1,187.7 (submitted)
- default had 1,190.4, so -0.2 %. bar is 0.5 %, didn't make it.
- ideas not tried: cross-exchange between routes, using the spare van to split the two worst routes, annealing instead of first improvement. 2-opt* (swapping route tails) probably the biggest win, we never got to it
