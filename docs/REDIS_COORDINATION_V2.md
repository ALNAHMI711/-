# Redis coordination contract

Redis is short-lived coordination only. PostgreSQL remains the durable source of truth.

Lease acquisition uses atomic `SET NX EX`; renewal and release require owner-checked atomic operations. Redis values contain only opaque worker/job lease identifiers, never OAuth tokens or platform passwords.
