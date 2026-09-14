# Worker Replay Protection

Worker envelopes use HMAC-SHA256 for authenticity and a short `expires_at` window for freshness. After identity, expiry, and HMAC validation succeed, the transport layer atomically claims `(worker_id, message_id)` through a replay guard.

Production Redis uses an atomic Lua claim with a TTL equal to the remaining envelope lifetime. A duplicate message is rejected before command execution. Invalid or unauthenticated messages never populate replay state.

Redis stores only opaque worker/message identifiers and a constant marker. It must never contain platform passwords, OAuth tokens, API keys, or other credentials.

The GitHub Actions quality gate runs the Redis integration test against `redis:7-alpine` so replay protection is tested with a real Redis server, not only an in-memory substitute.
