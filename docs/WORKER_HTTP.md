# Worker HTTP boundary

The worker transport is exposed through an internal FastAPI endpoint:

`POST /internal/workers/{worker_id}/messages`

The request contains only the transport envelope (`message_id`, timestamps, `body`, and `authentication_tag`). The worker secret is resolved server-side and is never accepted in the request.

Validation order:

1. Parse and validate the envelope shape.
2. Resolve the server-side secret for the requested worker.
3. Validate worker identity, expiry, and HMAC-SHA256 authentication.
4. Atomically claim the `(worker_id, message_id)` replay key.
5. Only after all checks pass, hand the envelope to the application handler.

Expected failures:

- `400` malformed/expired message.
- `401` authentication failure.
- `403` worker identity rejection.
- `409` replayed message.
- `202` accepted and handed to the handler.

Production deployments should provide a persistent secret resolver and `RedisReplayGuard` rather than the in-memory implementations used by tests/local development. The handler must remain responsible for application-level authorization and must never interpret the HTTP body as an arbitrary shell command.
