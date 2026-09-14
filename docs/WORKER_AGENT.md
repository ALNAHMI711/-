# Worker Agent

The Worker Agent is the execution-side contract for Mashahid compute nodes.

## Security boundary

- A worker connects **outbound** to the control plane; the dashboard does not expose Docker or SSH controls directly.
- Enrollment credentials are represented by an opaque `enrollment_ref` only.
- Raw enrollment tokens, passwords and private keys must never be stored in `WorkerAgent`, serialized to logs, or committed to Git.
- Production enrollment and transport must use authenticated HTTPS/TLS and a secret manager or encrypted credential vault.

## Lifecycle

`UNENROLLED -> ONLINE -> OFFLINE/ERROR/DRAINING`

A valid heartbeat marks the worker online and clears a previous transient error. Draining workers remain controllable but should not receive new jobs; routing policy belongs to the compute-node manager.

The phone is only the remote control surface. Jobs continue on workers after the browser or phone is closed.
