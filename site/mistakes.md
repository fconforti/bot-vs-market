# Mistakes

Append-only. Every entry: what was wrong, what it cost, and what rule would have
prevented it. Written by the agent when a past decision turns out to be wrong, and by
the owner when the agent missed one. Lines are never removed.

_No mistakes recorded yet. The first live run has not happened._

## 2026-10-16 (dry run, replayed on 2026-10-18): the algorithm cannot run in dry-run mode

- **What was wrong:** the build session on 2026-10-18 declared the pipeline ready without
  running the daily session end to end in dry-run mode. `strategy/current.py` looks up the
  latest snapshot with `dry_run=False` hard-coded, so in a dry run it ignores the dry-run
  snapshot it was just given and exits with "no portfolio snapshot found". The first dry run
  therefore produced no signals and no proposed orders.
- **What it cost:** no money. One dry run that could not test the guardrails preview path,
  which was the point of the dry run, and one more owner-side fix before the first live day.
- **Rule that would have prevented it:** a test (or a step in the build checklist) that runs
  `bin/snapshot.py --dry-run` followed by `strategy/current.py` under `FINANCE_DRY_RUN=1` and
  asserts a JSON result. More generally: no component is "done" until the dry-run path has
  been exercised through the same entry points the session uses.
