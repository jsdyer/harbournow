# Ten new CoolCode tools: release integration

This bundle accompanies `harbournow`, `screenplaces`, `wikitrails`,
`addresschronicle`, `torrentlens`, `skygeometry`, `budgetmirror`, `movebench`,
`canadapulse` and `planehere`. Repository writes in this round are limited to these
ten repositories, as requested. Existing tool and hub repositories are unchanged.

## Shared Worker

`ten-tools-worker-base.js` is the reviewed download of the owner's deployed Worker
on November 25, 2026. It already contains all 267 registered IDs. The only difference
from the previous reviewed hub Worker is the owner's addition of these ten IDs.

`ten-tools-worker.js` adds the Screen Places and Plane Here public API handlers to
that baseline. It preserves the other tools, administration, visit counting,
issue reporting, and existing DB use. Do not replace the existing Worker with either
app's small gateway module: deploy the complete generated Worker file.

The existing bindings are retained. Required secrets are
`TMDB_READ_ACCESS_TOKEN` and the optional `ADSBLOL_API_KEY`. The latter is optional:
anonymous provider access has a smaller allowance and may also be temporarily
unavailable. A rate-limited request must not be retried without the key to bypass
the provider's limit. No AISStream key belongs in the public frontend.

Deploy by replacing the current Cloudflare Worker code with the complete
`ten-tools-worker.js`, saving and deploying. Keep the current DB binding and all
secrets. Deployment is a separate manual owner action; generating this file does
not deploy it. Before a later deployment, compare the current deployed source to
this reviewed baseline and any intervening owner changes.

Check `/registry`, `/api/status`, `/api/planehere/nearby?lat=44.65&lon=-63.57&radius=25`
and a real title in Screen Places after deployment. Status reports only credential
presence, never their contents. A successful status request does not prove provider
credentials work; verify a real response as well.

On November 25, 2026, the owner-deployed Worker returned successful live responses
from both new APIs: TMDb supplied the title, poster and rating for *88 Minutes*,
and adsb.lol supplied a current, valid response using the configured key. An empty
aircraft list is permitted; it is not evidence of comprehensive reception. The
generation manifest retains its original pre-deployment flags as a release record.

## VPS

Harbour Now's collector runs on the owner's VPS, not brix. Follow
[`../docs/VPS.md`](../docs/VPS.md). The initial published frontend is not evidence
that the collector is collecting ships. The owner installed it at
`https://harbour.hackme.ca`; HTTPS and CoolCode CORS were verified on November 25,
2026. The default frontend now uses that origin. The initial collector needs the
published subscription-confirmation fix and a VPS rebuild; fresh observations
remain to be verified after that restart.

## Deferred central integration

### Operations inventory for these ten repositories

[`ten-tools-operations.json`](ten-tools-operations.json) records the actual workflow
cron expressions, dispatch inputs, guard allowlists, reviewed freshness probes and
workflow-file hashes. Its `repositories` and `freshness` fields use the central
registry structures and are additions to merge, not replacements for the existing
registries. Times below are UTC, matching GitHub Actions schedules.

| Repository | Scheduled source collection | Published freshness field | Maximum age |
| --- | --- | --- | --- |
| `screenplaces` | Thursday 09:30 · `30 9 * * 4` | `/screenplaces/data/catalogue.json` → `fetched_at` | 10 days |
| `addresschronicle` | Day 2 of each month, 08:17 · `17 8 2 * *` | `/addresschronicle/data/status.json` → `checked_at` | 40 days |
| `budgetmirror` | Day 20 of each month, 14:17 · `17 14 20 * *` | `/budgetmirror/data/status.json` → `checked_at` | 40 days |
| `movebench` | Day 20 of each month, 14:47 · `47 14 20 * *` | `/movebench/data/status.json` → `checked_at` | 40 days |
| `canadapulse` | Daily 16:23 · `23 16 * * *` | `/canadapulse/data/status.json` → `checked_at` | 48 hours |
| `harbournow` | Continuous collector on the owner's VPS; no GitHub schedule | `/api/v1/health` → `last_observation_at`, `feed.state`, `observations_fresh` | Initially 15 minutes, reviewed against actual coverage |
| `wikitrails`, `planehere` | On-demand API requests; no scheduled collection | None | Not applicable |
| `torrentlens`, `skygeometry` | Local browser calculations; no scheduled collection | None | Not applicable |

Each of the five scheduled apps uses `.github/workflows/pages.yml`, retains
`workflow_dispatch`, and has a separate `.github/workflows/schedule-guard.yml`
allowlisting both files. The manifest records each guard's actual cron. Screen
Places requires watchdog dispatch input **`refresh: "true"`**, because its manual
dispatch defaults to an offline rebuild. The other four collector dispatches need
no inputs. Freshness refers to a successful source check/fetch, not a source's
historical reference year or a website build timestamp.

The central watchdog is **not yet registered for these five new collectors**,
because modifying the existing hub repository was excluded from this round.
Their native GitHub schedules and guards can run independently after publication.
Harbour Now's probe is `https://harbour.hackme.ca/api/v1/health`;
Docker liveness alone must not be reported as healthy AIS collection. After the
later central merge, verify dispatch permissions and a real successful refresh for
each scheduled target rather than inferring health from these definitions.

The new repositories' `tool.json` files and marked README guides are the reviewed
inputs for the next hub update. `ten-tools-catalogue.json` collects the ten records.
The finalized workflow inventory and freshness definitions are in
`ten-tools-operations.json`. They are additions to existing registries, not
replacement files.

The existing hub catalogue, generated homepage/README/sitemap, repository audit and
independent watchdog registrations have not been modified this round. The new
Pages sites can work at their own paths before those discovery changes are applied.
Native GitHub schedules and their inactivity guards remain separate from the
independent watchdog; a schedule is not proof of a successful refresh.

When the owner authorizes the later hub round: import these tool records and guides,
merge the operations inventory/freshness definitions, reconcile the repository
audit, incorporate the app-owned gateways into the central Worker generator, run
the hub lifecycle checks, and regenerate homepage, sitemap and watchdog targets.
Retire this temporary bundle only after the central source reproduces the reviewed
deployed Worker. Do not lose the ten new IDs when regenerating from the old hub.

## Rebuild

Check out the ten repositories as sibling directories, then run:

```sh
python3 harbournow/ops/build-ten-tools.py --checkouts-root .
```

This reads the ten checkouts and writes only this `ops` directory. The manifest
records source hashes and explicitly leaves deployment status unverified until
the owner deploys and a real check is recorded.
