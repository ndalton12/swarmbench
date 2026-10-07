# Known issues (planning pool)

- **OPS-412** results-cache not mounted on worker hosts since the storage
  move ({{date:-9d|date}}). submit-plan writes locally, files are synced up when the
  mount is back. ETA "this week" per infra. (BO)
- score-plan on very large plans (> 400 drops) takes ~20 s because of the
  pure python distance loop. Fine for now.
- Handheld export rounds shift times to 5 min, so a plan at 509 min can show
  as 510 on the handheld. Still valid.
- `tools/nn_plan.py` ignores the spare van flag. Don't use its output as is.
- Worker hosts reboot Sunday 03:00 for patches.
