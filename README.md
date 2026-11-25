# Harbour Now

Identify ships observed around Halifax Harbour and Vancouver/English Bay. Explore a map, search vessel details, inspect recorded tracks, and review harbour entries/exits and anchorage observations.

**Web interface:** <https://coolcode.ca/harbournow/>

**VPS installation:** [docs/VPS.md](docs/VPS.md)

The frontend is ready to publish on GitHub Pages. Live observations require the separately installed collector and a configured HTTPS endpoint. An unconnected page explicitly shows that state; it never presents example ships as real observations.

<!-- coolcode:guide -->
Choose Halifax or Vancouver, search a vessel name or MMSI, and select a ship for details and its recorded track. Older positions are hidden initially; enable “Show older positions” to inspect them with their original timestamps. Entries/exits require consecutive observations across a configurable boundary, and a first sighting is not an arrival. “Time observed at anchor” begins after compatible observations in an approximate anchorage zone and resets after a long gap. Connect the HTTPS address of an installed Harbour Now collector under “Connect a collector”; never enter the AISStream key in the browser.
<!-- /coolcode:guide -->

## Included

- Responsive map with OpenStreetMap tiles, selectable vessels, zoom/pan and tracks.
- Name/MMSI/callsign/destination search, vessel-type filters and explicit stale observations.
- Movement diary, 24-hour / 7-day / 30-day views and CSV export.
- One compressed AISStream WebSocket for all configured areas; exponential reconnect backoff.
- Server-side SQLite storage, bounded read-only JSON API, retention cleanup and Docker health check.
- No visitor accounts or browser-exposed service key.

## Data and interpretation

[AISStream](https://aisstream.io/documentation) aggregates AIS observations. Receiver coverage varies and the service has no delivery/uptime guarantee. Not all vessels transmit AIS, not all transmissions are received, and destinations are vessel-reported text. This tool is not for navigation.

The harbour/anchorage polygons are approximate observation areas, not official port limits or assigned anchorages. An entry/exit requires two consecutive reports on the new side of a boundary. A gap longer than 10 minutes or a boundary configuration change resets continuity without inventing an arrival. Anchorage classification requires the configured anchorage zone plus reported anchored status or speed of at most 0.5 knots, sustained across at least two minutes of observations. A new gap resets the timer; this is not total voyage/port waiting time.

Source observation times remain separate from API generation times. Missing source timestamps use collector receipt time; invalid, future or very old supplied timestamps are rejected. Track points are retained at up to one per minute per vessel, and lines break over gaps. By default observations/events expire after 30 days. Historical events carry a boundary fingerprint. They are observations made by this installation, not a comprehensive historical AIS archive. Confirm AISStream's terms for your intended public redistribution/retention before publishing a historical dataset.

## Local development

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
node --test tests/*.test.mjs
python3 -m unittest discover -s tests -v
python3 scripts/build.py
python3 -m http.server 8000 --directory dist
```

The offline build requires Python's standard library only. The collector additionally needs the pinned `websockets` package. For a local collector without a key (explicit offline status), use:

```sh
DATABASE_PATH=./data/harbournow.sqlite PORT=8090 python3 -m collector.app
```

Open `http://localhost:8090/` for the collector-hosted interface. It detects the same-origin API automatically. To exercise only the Pages frontend, use the static server and enter `http://localhost:8090` in “Connect a collector”; include the static origin in `ALLOWED_ORIGINS` first.

## Expand or customize

Edit `config/harbours.json`. Add an object with a unique `id`, `name`, IANA `timezone`, map `center` and `zoom`, `subscription_bbox` (two `[latitude,longitude]` corners), and `boundary`/`anchorage` polygons. Keep subscription boxes wider than the observation boundary so crossings can be observed. Polygon edges use straight segments in latitude/longitude; antimeridian regions are not supported. The test suite exercises a third configured harbour.

The collector reads configuration at startup. After changes run the tests and build, then `docker compose up -d --build`. Existing event records remain dated and retain their boundary fingerprint; changed geometry resets current continuity. Preserve IDs if you want earlier events to remain available through the same harbour selector. The built frontend reads the live collector's harbour list after connection.

Edit `web/config.json` to set the public `api_base` once the VPS HTTPS origin is ready, or leave it blank and connect per browser. `refresh_seconds` has a 30-second minimum. A connected origin is remembered only when the visitor chooses it. Do not put secrets in this file. Rebuild and publish via the Pages workflow.

## Publication and operations

The Pages workflow checks JavaScript logic, Python collector/builder behaviour and browser smoke tests before deploying `dist/`. PRs never deploy. The VPS collector is continuous; there is deliberately no GitHub scheduled polling job. Monitor `/api/v1/health`: `service: ok` means the HTTP process is alive, while `observations_fresh` and `feed.state` describe actual feed health. A Docker health check alone does not prove current AIS coverage.

Only this new repository is in scope for this release. Homepage/Worker/watchdog registrations in the existing central repo are a separate integration step; an unconnected VPS must not be labelled a completed live-data deployment.

## Privacy and credentials

`AISSTREAM_API_KEY` belongs only in the VPS `.env`. `.env`, databases, generated output and logs are excluded from Git and the container build. Server logs omit request queries, raw upstream payloads and exception text. The public API exposes selected observations only and has no administrative/write routes.

Search/filter inputs stay in the browser. Fetching observations sends requests to the selected collector; map views request OpenStreetMap tiles. API requests omit cookies and referrers. Optional local storage is namespaced `coolcode:harbournow:api`.

## API

All endpoints are GET/HEAD and return JSON. Parameters are bounded; invalid values return 400. Read endpoints use short public cache windows. Supported browser origins are an explicit allowlist; requests without an Origin header remain possible because this is public data.

| Route | Result |
| --- | --- |
| `/api/v1/health` | Service/configuration/feed state and last observation time, no credentials |
| `/api/v1/harbours` | Current public harbour geometries and display settings |
| `/api/v1/ships?harbour=halifax` | Up to 2,000 recent vessel records with timestamps/state |
| `/api/v1/events?harbour=halifax&hours=24` | Most recent 200 observed events within retention |
| `/api/v1/track?mmsi=123456789` | Up to 1,440 retained points from the last 24 hours |

See [VPS instructions](docs/VPS.md) for install, TLS, monitoring, upgrades and backups.
