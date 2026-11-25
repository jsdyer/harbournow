# Harbour Now maintenance

- Frontend source is in `web/`; the offline Python builder publishes only `dist/`.
- Continuous AIS collection belongs on the user's VPS. Never move its key into browser code or a scheduled GitHub sample that claims continuous history.
- Keep the key in a private VPS `.env`, never source or command arguments. Do not log upstream subscription payloads or exception text that could contain it.
- Treat source timestamps, receipt timestamps, API generation time and historical observation gaps distinctly. Initial discovery and gaps are not arrivals. Keep unconnected/stale states explicit.
- Configured areas, retention and source settings must be documented in README and `docs/VPS.md`. Preserve historical event dates and boundary fingerprints when geometry changes.
- Render all external text through `textContent`. Keep read API routes bounded and validate configuration, AIS messages, query parameters and browser origins.
- Run `node --test tests/*.test.mjs`, `python3 -m unittest discover -s tests -v`, and `python3 scripts/build.py`. CI additionally runs browser smoke tests and a Docker no-key health check.
- This release is limited to the new repositories. Do not modify other CoolCode repositories without user authorization; record integration follow-ups clearly.
