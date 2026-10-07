# Judge scanner definition cases

Each JSON file here is a hand-labelled example that documents, in plain terms,
what one scanner **should** and **should not** flag. They pin down the scanner
definitions so a later change to the wording can be checked against human
intent. They are *definition checks*, not a calibration set: the real-model
calibration (does the model actually answer this way?) happens later, once API
keys are available.

Each case file has this shape:

```json
{
  "scanner": "false_success",          // must match a key in judge/scanners.py
  "should_flag": [
    {"why": "...", "text": "transcript excerpt that is a clear violation"}
  ],
  "should_not_flag": [
    {"why": "...", "text": "excerpt that looks similar but is NOT a violation"}
  ]
}
```

The "should_not_flag" examples are the important ones: they are the near-misses
that separate *discussing* a bad idea from *doing* it, an honest report of
failure from a false claim of success, and ordinary software testing from
genuine evaluation-awareness.
