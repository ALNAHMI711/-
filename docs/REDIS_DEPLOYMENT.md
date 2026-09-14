# Redis deployment

The repository includes a minimal Redis service definition for local/container
use. Redis is intentionally configured without AOF persistence because it is a
coordination cache; durable job state belongs to PostgreSQL.

Production requirements:

- private network access only;
- TLS/authentication where Redis crosses a trust boundary;
- no platform credentials or OAuth tokens in Redis values;
- monitor memory, connection count and eviction/error rates;
- PostgreSQL remains authoritative if Redis is unavailable.
