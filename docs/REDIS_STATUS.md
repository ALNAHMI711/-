# Redis status

Redis coordination has been added as an explicit infrastructure boundary.

Production rule: PostgreSQL remains authoritative for durable state; Redis is
only for expiring coordination leases. The dashboard must report Redis health
separately from database health.
