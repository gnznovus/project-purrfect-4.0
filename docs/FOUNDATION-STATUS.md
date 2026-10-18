# Purrfect 4.0 — Foundation prototype status

Updated: 2026-10-18. This is a **prototype milestone record**, not a production-readiness declaration.

## Current architecture

- **Purr Assistant** — WordPress plugin / per-site Child: admin Control Center, floating chat, active-product discovery, component-owned heartbeat, registry, native update integration, validated local knowledge cache.
- **Purr** — Python-side commander: scoped product/WordPress guidance, conversation and troubleshooting; deterministic path tested, optional Ollama `llama3.2:3b` routing.
- **Sophia** — durable shared approved knowledge: SQLite revision history, validated checksummed leases, per-site last-good cache; trusted operator CLI publication rather than a complete authenticated review workflow.
- **Aurora** — separate future execution worker; **not integrated** into the WordPress prototype or current health chain.

Names above are user-facing; underlying `purr-child`, `purra`, `sophira` and other technical identifiers remain for compatibility.

## Milestone evidence

| Goal | Implementation / validation |
| --- | --- |
| 1.1–1.10 Foundation | Merged [PR #1](https://github.com/gnznovus/project-purrfect-4.0/pull/1); two-site Docker WordPress lab, registry, knowledge leasing, sync and recovery acceptance; automated CI and focused live WordPress tests |
| 1.11 UI polish | Merged [PR #3](https://github.com/gnznovus/project-purrfect-4.0/pull/3); public labels, P2/U2 artwork, hover eyes and blink preference behavior accepted through browser checks. Auto-blink under `no-preference` not separately observed |
| 1.12 Portable bootstrap | Merged [PR #4](https://github.com/gnznovus/project-purrfect-4.0/pull/4); non-destructive root `bootstrap.ps1`, WordPress provisioning, Ollama model management and inference probe, empty-catalog demo seeding, PowerShell syntax CI. **Fresh Windows laptop E2E and repeat run not yet performed** |
| Main-branch CI | [Successful run](https://github.com/gnznovus/project-purrfect-4.0/actions/runs/39120678187) after integration; not a substitute for fresh-machine Ollama/WordPress acceptance |

## How the local lab works

```text
WordPress Site A (8084)  ─┐
                          ├── Purr (Python service) ── Sophia (shared SQLite knowledge)
WordPress Site B (8083)  ─┘             │
      per-site Child, cache      Ollama (optional inference)
      registry + heartbeat
```

Site A and Site B have **independent WordPress volumes and Child caches**; Purr and Sophia share a local service/data volume. Sophia outages do not invalidate already verified local leases. Neither Purr nor Sophia currently exposes a hardened cross-machine authenticated production service contract.

## Portable setup

Requires Windows/PowerShell, Git, Docker Desktop in Linux container mode, network access for images and `llama3.2:3b`, and available ports. No dedicated GPU required; CPU may be slow.

```powershell
git clone https://github.com/gnznovus/project-purrfect-4.0.git
cd project-purrfect-4.0
.\bootstrap.ps1
```

Optional second site: `.\bootstrap.ps1 -SiteB`.

A fresh WordPress site prompts for a local admin password. Bootstrap preserves named Docker volumes and existing WordPress users/knowledge on repeat runs. It fails clearly on Ollama inference errors instead of silently reporting success. Model download and real inference are *implemented checks*; neither has been acceptance-tested on the new office hardware.

Never run `docker compose down -v`, remove named volumes, or execute bootstrap against a real production WordPress site.

## Still open

1. Execute real fresh-clone and repeat-run acceptance on office laptop; test functional chat and health.
2. Validate real Ollama response quality, CPU latency and resilience beyond one smoke prompt.
3. Improve security/deployment boundary for independent Purr/Sophia services and authenticated knowledge approval workflow.
4. Validate real plugin release downloads/updates and rollback with trusted artifacts, beyond no-op mock checks.
5. Expand product knowledge and real integrations; Aurora worker integration remains separate future work.

**Milestone language:** Foundation prototype **implemented and locally validated in scope**; portability code **merged, pending office acceptance**; **not production complete**.
