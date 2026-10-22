# ADR-0013 Approval classes A-D and plan files

**Status:** Accepted, pending owner decision OD-10 (confirmation of the agent boundary).

**In plain words:** Every command has an approval class. A reads only. B only adds things such as backups, and may run unattended. C changes something and needs the instance name typed, or a plan the owner approved. D can lose data and needs a typed challenge on a real terminal, never a saved plan. AI assistants never get class D.

## Context

The predecessor's approval model was interactive-only and blocked scheduled backups with exit 20. An approval hash that also unlocks purge lets an agent destroy data (Lens A on `container`).

## Decision

A read-only, B non-destructive (unattended), C changing (typed instance name on a terminal, or `ingat apply <hash>` of a saved plan), D destructive (terminal only, phrase plus random challenge; `apply` is never accepted for class D, `disposable` instances included). `start`, `stop`, `restart` are class C (Lens A must-fix). Owner-gated env changes, data-service image changes, restore into a live instance, data rollback, generation and image prune, purge and `resolve` are class D ([LIFECYCLE.md](../LIFECYCLE.md) §2). Adoption has no class D step, because Ingat never stops the foreign project: its import is class B and its restore into a never-deployed instance class C ([ADR-0024](0024-adoption-by-payload-import.md)). `disposable` only lets purge skip its restore-test.

## Alternatives

A policy file of grants (rejected: a blocker in the predecessor). `--approve` for every class (rejected: agent purge). `apply` for class D on disposable instances (rejected: staging instances such as `pg-staging` and stateless sites are disposable, so an agent holding a hash could purge or restore over them).

## Consequences

Operations agents can prepare everything and apply class C with the owner's hash; class D is meant for the owner alone. The CLI cannot tell an agent from the owner (an agent with a pty can type a challenge), so the boundary holds only for agents that obey it; the agents' own tool deny rules enforce it (owner decision OD-10). Development agents in the Ingat repository never touch a real host ([CLAUDE.md](../../CLAUDE.md) §6).
