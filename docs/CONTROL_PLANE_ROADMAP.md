# Control Plane Roadmap

Current foundation:

- OAuth state/session safety
- Account linking and verification metadata
- Credential reference boundary
- Free/private compute-node registry
- Secure outbound worker-agent contract
- Job lifecycle with idempotency and leases
- UTC-safe scheduler contract

Next implementation gates:

1. Persistent PostgreSQL models/repositories.
2. Redis-backed distributed leases and queue coordination where required.
3. Worker command polling over authenticated HTTPS.
4. Job routing + retry/failover integration.
5. FastAPI authentication and mobile-first RTL dashboard.
6. Platform OAuth/token-exchange adapters and encrypted secret storage.
7. Upload Mode pipeline (media analysis, transcode, metadata, publish).
8. AI Autopilot orchestration with project-specific rules.
9. Official platform publishing adapters and verification/monetization status flows.
10. Docker deployment, health checks, monitoring and backup/restore tests.

No production publishing or autonomous execution is enabled by these domain-only steps. Each gate must have tests and a passing CI run before the next gate is started.
