# Initial historical coverage findings — 2026-11-02

## Decision

Public data is sufficient to begin a price/liquidity modelling prototype. Prefer
hourly transaction-side averages as the initial training source. A multi-year
hourly backfill appears feasible, but this sparse audit does **not** establish
continuous retention, completeness, or execution/fill-time labels.

No RuneLite client changes, model training, or bulk download were performed.

## Verified observations

The 19-probe audit completed at 20:03 UTC with HTTP 200 for every request:
17 non-empty responses and two empty historical buckets. Responses are cached
locally under `output/cache/`; full provenance and statistics are in
`output/report.json`. These runtime files are deliberately git-ignored.

### Guide-price histories

| Item | Earliest returned observation | Records | First non-null volume | Missing volume records |
| --- | --- | ---: | --- | ---: |
| Abyssal whip (4151) | 2015-03-28 | 4,397 | 2018-09-25 | 1,268 |
| Nature rune (561) | 2015-03-28 | 4,374 | 2018-02-19 | 1,037 |
| Twisted bow (20997) | 2017-01-06 | 3,767 | 2018-09-25 | 639 |

All three histories extend to 2026-11-02. Their median spacing is one day, but
there are irregular intervals and gaps; these are not complete daily grids.
These guide prices are not interchangeable with instant-buy/sell averages.

### Real-time item series

For all three items:

- `lookback=7d`: 168 hourly observations, 2026-10-26 20:00 through
  2026-11-02 19:00 UTC.
- `lookback=1y`: 365 daily observations, 2025-11-02 through 2026-11-01.
- No missing timestamp intervals or duplicate timestamps in those responses.
- The twisted-bow hourly series contains one null sell-side average. A complete
  timestamp grid therefore does not imply complete price observations.

### Historical all-item buckets

Each probe was at 00:00 UTC. Returned timestamps matched requested timestamps.
Counts below are item IDs present, not trades or guaranteed full-market coverage.

| Date | Items in 5-minute bucket | Items in hourly bucket |
| --- | ---: | ---: |
| 2026-11-01 | 1,923 | 3,361 |
| 2025-01-01 | 1,459 | 2,818 |
| 2023-01-01 | 1,427 | 2,737 |
| 2021-04-01 | 1,614 | 2,852 |
| 2021-02-01 | 0 | 0 |

All three sampled items appear in the April 2021 buckets. Twisted bow is absent
from the January 2023 five-minute bucket and has no buy-side price in the January
2025 five-minute bucket. Preserve absence/nulls rather than invent prices or
assume missing records mean zero market-wide volume.

The February 2021 empties do not locate an exact retention boundary. The successes
prove that those specific old buckets are retrievable, not that every intervening
bucket exists.

## Verification

- 16 offline unit tests passed.
- Pyright: zero errors or warnings for the audit and tests.
- All 19 live results reproduced exactly from cache (apart from the cache flag),
  with network access mocked to fail during replay.

## Next dataset recommendation

Start with a bounded hourly pilot and a missing-data manifest before expanding to
multiple years. Arrange substantial historical access with the Wiki maintainers.
Keep guide prices separate, retain original responses, and record interval start,
interval end, retrieval time, source regime, and item ID. Evaluate chronologically
and account for historical tax/buy-limit rules. Public aggregates cannot establish
whether our own offers would fill; collect those labels separately when a manual
trading-assistant plugin exists.

See [README.md](README.md) for source documentation, commands, and limits.
