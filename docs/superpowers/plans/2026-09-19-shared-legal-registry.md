# Shared legal-event registry

Goal: retain explicitly human-reviewed legal events outside expiring workspaces and let users inspect the event-derived state at a chosen date.

Contract: no automatic promotion, no claim of complete/current law. Publication is a separate admin+CSRF+confirmation action over an owned saved review. Revalidate the immutable evidence snapshot. Publish only public source quotes/relationships, no workspace notes or IDs in public output. Withdrawal retains audit history and removes the batch from public calculations. Mongo writes are atomic per review batch; database failures remain unavailable, never empty/healthy.

- [ ] Pure projection and publication validation tests: as-of, partial effects, relationships, unknown, private-field exclusion, withdrawn records.
- [ ] Mongo store with idempotent publication, explicit withdrawal, bounded reads and embedded actor/time audit.
- [ ] Admin publication/withdrawal UI, public lookup, reader/search links; existing workspace review stays private unless explicitly published.
- [ ] Focused RED/GREEN, stable diff review, broader suite, real read-only DB/browser checks, docs and commits.

Live human-only publication will not be performed by the agent. Unit fixtures do not stand in for verified legal data. Initial public coverage can be empty and must say so. No corpus/vector mutation.
