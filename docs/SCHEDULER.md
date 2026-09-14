# Scheduler

The scheduler stores timezone-aware execution times and evaluates due schedules in UTC.

Paused schedules never emit jobs. A due schedule emits at most once in this reference implementation; production recurrence and durable claiming must be backed by the database so multiple control-plane instances cannot emit duplicates.

The scheduler should create queue jobs using deterministic idempotency keys, then let the Job Queue route execution to healthy workers.
