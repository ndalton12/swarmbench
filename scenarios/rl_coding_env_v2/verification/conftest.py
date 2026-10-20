# Executable task suites are calibrated exclusively through the isolated executor.
# These directories are fixture data, not host-side pytest modules.
collect_ignore = ["vendor", "tasks"]
