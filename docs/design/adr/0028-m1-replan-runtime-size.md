# ADR-0028 M1 re-plan: runtime size

**Status:** Accepted (owner, 2026-10-15), under the 1.5× stop rule of [ROADMAP.md](../ROADMAP.md) §3.

**In plain words:** Milestone M1 turned out bigger than first estimated: about 6,600 lines of code instead of 3,000, with a stop for review at about 10,000. What M1 delivers did not change.

## Context

M1 was estimated at about 3,000 runtime lines, with a stop for a re-plan at 4,500 (1.5×). When the slice 1 foundations were written (brand, errors, records, templates, the full schema 1 manifest and instance models, bundle format, gate, retention, store, runner, override, git and HTTP probe adapters, plan, journal and approval), they measured 2,227 runtime lines (non-blank, non-comment Python), with the manifest model alone at 575 because schema 1 parses in full from v0.1 ([MANIFEST_SPEC.md](../../app-developers/MANIFEST_SPEC.md)). A bottom-up estimate of the remaining M1 modules (Docker and Compose adapters, Compose policy, executor and steps, the planners for host, init, status, prepare, deploy, lifecycle, tasks, backup, verify, drill, prune and selftest, the CLI with follower, `install.sh` and `facts.sh`) gives about 6,600 runtime lines for M1, about 2.2× the estimate. The module budgets of [ARCHITECTURE.md](../ARCHITECTURE.md) §5.1 already sum to about 9,000 lines for M1-M3, and M1 contains most of that machinery: the executor, the step set, the journal, the isolated drill and the data-changing update all land in M1, because the first real consumer needs them.

## Decision

The M1 estimate becomes about 6,600 runtime lines and its stop line 1.5× that, about 10,000. The scope of M1 is unchanged. The code stays as small as each rule allows: no speculative options, no unused helpers, no abstraction without two users. The 600-line module limit, the consumer-need rule and every safety floor are unchanged. The M2-M5 estimates are not revised now; each is re-checked against measured M1 sizes when it starts.

## Alternatives

Cut M1 scope to fit 4,500 lines by moving the drill, the config-only change and `scheduled status` to M2 (rejected by the owner: `lite-test` could not meet the M1 exit gate, which needs a drill and a data-changing update). Stop at 4,500 for review (rejected by the owner: the estimate, not the scope, was wrong, and the bottom-up count shows no feature beyond the M1 list).

## Consequences

The MVP and completion totals in [ROADMAP.md](../ROADMAP.md) are low by roughly the same factor until each milestone is re-estimated. A further overrun past about 10,000 lines in M1 stops again for a re-plan ADR.
