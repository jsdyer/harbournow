# Install Harbour Now on your VPS

This runs on your VPS, not brix. GitHub Pages hosts the public browser interface; the VPS maintains one AISStream connection and its SQLite history. The same container can also serve the interface directly.

## Requirements

- Linux VPS with Docker Engine and the Docker Compose plugin already installed.
- Start with 1 CPU, 512 MB available RAM and 5 GB free disk; monitor actual database growth as traffic/coverage varies.
- Outbound HTTPS/WSS to `aisstream.io` and access to image/package registries while building.
- A hostname such as `harbour.yourdomain.ca`, DNS pointed at your VPS, and an HTTPS reverse proxy.
- Your existing AISStream key. A Cloudflare secret cannot automatically be read by this VPS; put the same key into the VPS environment below.

The container's port binds to **127.0.0.1:8090**. Do not open 8090 to the Internet. Only your HTTPS reverse proxy should be exposed. One connection subscribes to both configured harbour areas; AISStream permits only three subscribed connections per account. Avoid running several copies with the same key.

## 1. Install the application

Run as your normal Docker-capable deployment user:

```sh
git clone https://github.com/jsdyer/harbournow.git
cd harbournow
umask 077
cp .env.example .env
nano .env
```

Set these values in the editor:

```dotenv
AISSTREAM_API_KEY=your_actual_key
ALLOWED_ORIGINS=https://coolcode.ca,https://jsdyer.github.io,https://harbour.yourdomain.ca
```

Do not paste the key into a shell command, GitHub source, frontend settings, or a screenshot. `.env` must remain private (`chmod 600 .env`). Include exact origins without trailing slashes. For testing a static page locally, temporarily add its exact origin, such as `http://localhost:8000`.

Start:

```sh
docker compose up -d --build
docker compose ps
docker compose logs --tail 50 harbournow
curl --fail http://127.0.0.1:8090/api/v1/health
```

The health response should contain `configured: true`. A connection may take a moment to establish; look for `feed.state: connected` and `compression_confirmed: true`. `observations_fresh: true` appears only after valid observations arrive. A reachable service with no observations is not proof that your selected harbour has receiver coverage.

The container runs as UID/GID 10001, drops capabilities, uses a read-only root filesystem and writes only to its named data volume. Initial named-volume ownership comes from the image's `/data` directory. If you replace it with a host bind mount, create that directory with owner `10001:10001` first.

## 2. Put it behind HTTPS

Use your existing reverse proxy. For Caddy installed on the host, add this site to its Caddyfile (replace the hostname):

```caddyfile
harbour.yourdomain.ca {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8090
}
```

Then validate and reload your Caddy configuration. If you already use Nginx/Apache, proxy the entire hostname to `http://127.0.0.1:8090`, retain your existing TLS certificate setup, apply normal request/time/connection limits and avoid caching `/api/v1/health`. No WebSocket proxy upgrade is needed: the collector's upstream WebSocket is outbound; browsers use ordinary JSON requests.

For your Apache/LAMP setup, an equivalent HTTPS virtual host is:

```apache
<VirtualHost *:443>
    ServerName harbour.yourdomain.ca
    SSLEngine on
    SSLCertificateFile /path/to/your/existing/fullchain.pem
    SSLCertificateKeyFile /path/to/your/existing/privkey.pem

    ProxyRequests Off
    ProxyPreserveHost On
    ProxyTimeout 20
    ProxyPass / http://127.0.0.1:8090/ connectiontimeout=5 timeout=20
    ProxyPassReverse / http://127.0.0.1:8090/
</VirtualHost>
```

This requires Apache's `proxy`, `proxy_http` and `ssl` modules. Replace the hostname and certificate paths with your existing ones, validate using your platform's `apachectl configtest`, then reload Apache through your normal service management. Keep your existing HTTP-to-HTTPS redirect and TLS policy. These are configuration examples; the application does not change your web server or certificate setup.

Check through the public hostname:

```sh
curl --fail https://harbour.yourdomain.ca/api/v1/health
curl --fail 'https://harbour.yourdomain.ca/api/v1/ships?harbour=halifax'
curl --fail -i -H 'Origin: https://coolcode.ca' https://harbour.yourdomain.ca/api/v1/health
```

The final response must include `Access-Control-Allow-Origin: https://coolcode.ca`. This is an explicit public-read API, not an authenticated private backend; CORS is not access control for non-browser clients. The built-in server bounds active connections, request sizes, query parameters and request rates; use your reverse proxy's limits for Internet-facing traffic.

## 3. Connect the public frontend

Open <https://coolcode.ca/harbournow/>, expand **Connect a collector**, and enter:

```text
https://harbour.yourdomain.ca
```

Choose **Remember this address on this browser** if wanted. Do not enter the API key. The map, vessel list and movement diary should populate when your collector receives observations.

To make that the default for all visitors, set `api_base` in `web/config.json` to your HTTPS origin, commit that public URL, and let GitHub Pages rebuild. Send the hostname back when testing is ready so the public default and end-to-end checks can be finalized. The repository intentionally does not guess a VPS hostname.

You can also visit `https://harbour.yourdomain.ca/` directly. The collector-hosted frontend detects its own API, so it does not need a separate saved address.

## 4. Verify actual collection

- Select each harbour and inspect the last observation times.
- Select a vessel to inspect its recorded track. History starts when this installation receives observations.
- Initial discoveries are not arrivals. Entries/exits need two consecutive reports crossing the configured boundary.
- Anchorage observations require at least two minutes of compatible reports. Missing reports longer than the continuity gap reset the timer.
- Check that a restart preserves the database and that the UI shows stale data honestly when the stream disconnects.

API methods and limits are listed in the root README. Coverage gaps must be expected; the service cannot replay missed AIS observations.

## Monitor and update

Docker's health check confirms that HTTP responds. Monitor the JSON fields separately: alert on `feed.state` staying outside `connected`, `configured: false`, and unexpectedly old `last_observation_at`. A quiet harbour may need a longer alert tolerance than a busy one. Add this HTTPS health URL to your existing watchdog only after it is deployed; there is no GitHub schedule to trigger.

Upgrade:

```sh
git pull --ff-only
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8090/api/v1/health
```

Stop without deleting history:

```sh
docker compose down
```

Do **not** add `-v` unless you intend to delete the named data volume. Retention cleanup runs every five minutes even while the upstream feed is disconnected. It removes old records but SQLite may retain allocated space for reuse.

## Back up SQLite

Use SQLite's online backup API inside the container rather than copying a live WAL database:

```sh
docker compose exec -T harbournow python -c "import sqlite3; source=sqlite3.connect('/data/harbournow.sqlite'); target=sqlite3.connect('/data/backup.sqlite'); source.backup(target); target.close(); source.close()"
docker compose cp harbournow:/data/backup.sqlite ./harbournow-backup.sqlite
docker compose exec -T harbournow python -c "from pathlib import Path; Path('/data/backup.sqlite').unlink()"
```

Store that backup privately and rotate it. It is ignored by Git. Re-check the provider's data-use/retention terms before publishing historical exports or mirroring the underlying database.
