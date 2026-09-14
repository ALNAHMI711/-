# Redis next gate

Before production rollout, run integration tests against a real Redis service,
verify failover semantics, add metrics for lease acquisition/renewal failures,
and wire health status into the control-plane readiness checks.
