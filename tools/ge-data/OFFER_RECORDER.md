# Local GE offer recorder

`GE Offer Recorder` is a standalone built-in plugin in this source tree. It is
**disabled by default**. Enable it explicitly in RuneLite's plugin list after
building/running this checkout. It does not depend on the Grand Exchange plugin
and has no trading controls or configuration beyond the plugin enable switch.

This is an observation tool for your own manual offers, not a trading bot,
recommendation engine, price feed, or reliable execution-time database. Nothing
here places, changes, cancels, collects, or otherwise interacts with offers.

## Output, privacy, and limits

Output is UTF-8 JSONL at:

```
~/.runelite/ge-offer-recorder/ge-offers-<random-run-UUID>.jsonl
```

On Windows, `~` is normally `C:\Users\<you>`. One file is created per enable
period, including enable periods spent logged out. All filesystem work and JSON
serialization run on a dedicated ordered background writer; client events only
copy primitive values into immutable snapshots and enqueue them. There is no file
per tick. A small `recorder.lock` file prevents simultaneous writers in this
output directory; its existence alone does not mean a writer is running.

The recorder does not read/store usernames, account hashes, profile keys, auth
tokens, chat, or IP addresses. It makes no network requests or uploads and
produces no game inputs. The profile-change event is used only as a boundary;
its identifying payload is ignored. Run/interval/offer IDs are local labels, not
account identifiers. A single run file can contain separate intervals from
different accounts; do not group it as one account's history.

Offer details and timestamps are still potentially sensitive. Files are plaintext
with normal operating-system permissions, not encrypted or automatically synced
by this plugin. Existing OS backup/sync settings remain your responsibility.
Inspect before sharing; move or delete files yourself while the plugin is off.

Hard limits (intentionally not configurable):

- Queue: 256 records. Queue overflow stops the writer rather than dropping events
  and then pretending to resume continuous observation.
- File: 16 MiB, with 1 KiB reserved for an explicit failure marker.
- Output directory: 128 MiB and 128 matching `ge-offers-*.jsonl` files across runs.
  The current file's budget also respects remaining directory space.
- Existing recordings are never automatically deleted or overwritten. There is no
  automatic rotation past these limits. Archive files **outside** this directory
  to free the budget, then disable/re-enable to start a fresh run. Multiple clients
  sharing the directory cannot record simultaneously.

A write error, lock conflict, overflow, or limit stops that run, emits an error to
the RuneLite log, and displays a local error dialog. Queue overflow drains the
already accepted prefix; the writer attempts a terminal `recorder_failure` record
for queue/byte limits. Disk/permission failures can prevent any marker or file
from being saved. Do not ignore the dialog or assume a missing failure marker
means success. Disable/re-enable only after resolving the cause. Rapid re-enabling
can encounter the old writer still draining and report a lock conflict.

Disable queues `interval_end`/`run_end` and drains asynchronously without blocking
the client. Ordinary writes reach the OS without application-level buffering;
they are **not fsync durability guarantees**. Client termination/crash or power
loss can truncate the final line or lose an unwritten suffix, including `run_end`.
Ignore a partial last JSON line and treat an absent `run_end` as an incomplete run.
An interval is not proven observed beyond its last actual snapshot/heartbeat.

## Supported worlds and lifecycle

Only `Client.getEnvironment() == 0`, a positive world number, and world-type flags
consisting solely of `MEMBERS` and/or `SKILL_TOTAL` (or no flags for ordinary F2P)
are supported. This deliberately conservative allowlist excludes Deadman,
seasonal/Leagues, fresh-start, beta, tournament, speedrunning, PvP and other flagged
worlds, even where some excluded worlds might share the main economy. Do not
combine these observations with special-world market data. World number,
environment and world-type flags accompany interval observations.

- On enable/login, capture all eight slots at the first logged-in **game tick**.
  This avoids reading live game state from the Swing lifecycle thread or taking a
  partially populated mid-login snapshot. Events before that tick are not recorded;
  the initial snapshot is only what is observable then.
- Offer-change events record changed snapshots. Identical snapshots are deduplicated.
- Approximately every 30 seconds of received game ticks, reread all slots (record
  changed values only) and emit a `heartbeat`. Heartbeats indicate client-side
  observation, not server connectivity proof or a new offer/fill.
- **Every** departure from `LOGGED_IN` ends the interval, including ordinary region
  `LOADING`, logout, disconnect and hopping. This intentionally over-segments rather
  than joining uncertain histories. Profile changes, world/context changes and
  gaps over 75 seconds between received game ticks also end the interval.
- The next supported logged-in game tick starts a new interval with fresh slot
  snapshots and new offer IDs. Old offer objects are never retained or joined
  across boundaries. On unsupported worlds an `observation_paused` record is
  emitted; no offer snapshots are taken there.

## Schema version 1

Each ordinary record has `schemaVersion`, `type`, `observedAt` (UTC ISO-8601
wall-clock observation timestamp), `runId`, increasing `sequence`, and `reason`.
Interval records also have `intervalId`, `world`, `environment`, `worldTypes`.
Optional values are omitted by Gson when absent. Sequence orders records even if
the system clock changes. The special writer-generated `recorder_failure` has
`schemaVersion`, `type`, `observedAt`, `runId`, `reason`, but no sequence or interval;
its time is the writer's failure-marker time, not an offer observation.

Types:

| Type | Meaning |
| --- | --- |
| `run_start`, `run_end` | Plugin enable/clean disable lifecycle, not login or placement. |
| `interval_start`, `interval_end` | Conservative observation boundary; end reason explains the detected gap. |
| `offer_snapshot` | Changed or initial slot value; includes `slot`, optional `offerId`, and nested `offer`. |
| `slot_unavailable` | Slot value missing/null, **not** an empty offer. Breaks that slot's identity. |
| `offer_boundary` | Old episode cannot safely continue; new snapshot follows with a new ID. |
| `heartbeat` | Periodic client-side observation checkpoint. |
| `observation_paused` | Unsupported world/environment; no active observation interval. |
| `recorder_failure` | Writer stopped; observation continuity is lost. May be absent on I/O failure/crash. |

`slot` is zero-based (0–7). `offer` is a value copy of the RuneLite API:

- `itemId`: integer item ID.
- `price`: **64-bit integer**, offer price per item.
- `totalQuantity`, `filledQuantity`: integer requested quantity and observed
  quantity bought/sold (`getQuantitySold()`), respectively.
- `spent`: **64-bit integer**, raw API `getSpent()` value. No inferred tax,
  profitability, proceeds adjustment, or execution-price computation is added.
- `state`: `EMPTY`, `BUYING`, `SELLING`, `BOUGHT`, `SOLD`, `CANCELLED_BUY`, or
  `CANCELLED_SELL` exactly as observed.

`offerId` labels a **local observed episode**, not a server-backed offer identity.
Within an interval, an active buy/sell can retain its ID through monotone fills
and a matching completion/cancellation. Empty/unknown slots, item/price/quantity
or side changes, decreasing filled/spent counters, and changed terminal offers
break identity. Identical repeated terminal values are deduplicated. An `EMPTY`
snapshot can carry the previous ID to close its slot episode, but is not an
inferred cancellation. A reuse that produces exactly indistinguishable values
without any observable intervening event cannot be detected; these IDs are not
ground truth. Do not infer repricing links from neighboring IDs.

### Interpretation rules

1. **Observation time is not placement time or fill time.** Initial snapshots may
   already be partially/fully filled. Updates can batch multiple fills. No precise
   waiting time, trade-by-trade history, or queue position is supplied.
2. **Cancellation is censoring**, not a zero-duration fill or a failed sale. Retain
   any observed partial quantity; the unfilled remainder has no observed natural
   completion time. Disappearance/collection alone does not prove cancellation.
3. **Offline periods and other gaps are unknown.** Never carry an offer ID, elapsed
   exposure, or a fill-time claim across intervals. Gap detection time is not
   necessarily the time observation first became unavailable. A heartbeat gap
   should also be treated conservatively even when a boundary record is missing.
4. **Repricing generally appears as cancellation/new offer.** No synthetic
   `reprice` event, parent link, inferred intent, or unobserved fill is invented.
5. Deduplication means no changed snapshot is not the same as no observation;
   use heartbeats, interval boundaries, missing-slot markers and failure signals.
   Never extrapolate ongoing observation past the last saved evidence.

This recorder does not automatically feed the Python market/forecast tools.
Joining personal episodes to price data requires separate, censoring-aware logic.

## Built client (user-run only)

The client including this plugin was packaged successfully as:

```
runelite-client/build/libs/client-1.13.6-SNAPSHOT-shaded.jar
```

From the repository root, a manual launch command is:

```
java -jar runelite-client/build/libs/client-1.13.6-SNAPSHOT-shaded.jar
```

This is a development build from this checkout, not an update to your regular
installed RuneLite. The plugin will not appear in an unrelated installed client.
Client startup and account login were **not** exercised; use your normal supported
account-login workflow. Packaging success is not a live-game validation or Plugin
Hub approval. No client was launched automatically.

To rebuild after changes, use `./gradlew :client:shadowJar`; the filename follows
the project version and may change in future checkouts.

## Manual verification (user-run only)

No live client/game interaction is required by the unit tests. For a manual check:

1. Build this checkout, confirm the plugin is off initially, then explicitly enable
   it on an ordinary supported world with an existing offer. Check a new JSONL file
   for `run_start`, `interval_start`, eight slot records and `heartbeat`.
2. Wait about 30 seconds. Expect another heartbeat, not a file/record every tick or
   duplicate unchanged snapshots.
3. If you independently choose to make a manual offer, inspect changed snapshots,
   partial quantities, completion and/or cancellation. The recorder must never
   move the mouse, type, click, recommend, or alter the offer.
4. Hop, log out/in, or switch accounts yourself. Confirm new interval/offer IDs
   even for the same slot/item/price and no recorded account/profile identifiers.
   A region load may also produce a new interval by design.
5. If you independently enter an excluded world, confirm `observation_paused` and
   no offer snapshots there. Return to a supported world for a new interval.
6. Disable, allow the writer to drain, then inspect `interval_end` and `run_end`.
   Preserve files before testing I/O failures. An unwritable directory or a second
   writer must show an error, not silently claim recording continues.

Focused automated tests:

```
./gradlew :client:test --tests 'net.runelite.client.plugins.geofferrecorder.*'
```

They use mocked client APIs and temporary local files, not OSRS or live accounts.
