## What and why

<!-- One change per pull request. What changed, and why. Link the issue: Fixes #123 -->

## How I verified it

<!-- Commands and their output: `make check`, and for detection changes the eval run below. -->

## Checklist

- [ ] Only fictional data, in code, tests, fixtures, screenshots and this description.
- [ ] Fails closed: a path that can't finish masking stops the request.
- [ ] No raw values in logs or errors (types, counts and placeholder ids only).
- [ ] Detection change: a run is recorded with `pii-guard eval ... --record <slug>`, before/after
      numbers are below, and the generated report is committed
      ([CONTRIBUTING.md](https://github.com/watt-mind/pii-guard/blob/develop/CONTRIBUTING.md#recording-a-benchmark-run)).
- [ ] An interface in [docs/contracts.md](https://github.com/watt-mind/pii-guard/blob/develop/docs/contracts.md) changed: that file is updated too.
