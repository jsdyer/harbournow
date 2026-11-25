# AISStream control-message fixture

`subscription-confirmation.json` reproduces the public subscription confirmation
example in <https://aisstream.io/documentation>, checked November 25, 2026.

The control envelope uses `Message.CompressionEnabled`, not the doubly nested
vessel-message convention. The connection regression test sends these fixture
bytes as a binary WebSocket frame, followed by a synthetic position message,
and proves the collector continues ingesting rather than reconnecting.

This is protocol test data, not a vessel observation or a recorded private stream.
