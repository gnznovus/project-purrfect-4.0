# Project Purrfect 4.0

A Python 3.14-based foundation for **product-grounded assistance** with a WordPress Child prototype. The first foundation integration (Goals 1.1–1.10) was merged in [PR #1](https://github.com/gnznovus/project-purrfect-4.0/pull/1).

**Status: validated local prototype, not production-ready.** The live Docker lab covers two separate WordPress sites, shared approved knowledge, a floating Purr assistant, and the Purr Assistant Control Center. CI exercises deterministic contracts and simulated WordPress components; actual LLM quality, external production systems, and real plugin-package upgrades are not covered.

## Components and boundaries

| Component | Responsibility | Implemented state |
| --- | --- | --- |
| **Purr Assistant** | WordPress-side product discovery, local cache, heartbeat, admin UI, and chat bridge | Working local WordPress plugin, version `0.2.0` |
| **Purr** | Product/WordPress guidance, scoped routing, conversation, and documented troubleshooting | Python HTTP prototype; deterministic by default, optional Ollama routing |
| **Sophia** | Shared approved knowledge, history, checksummed snapshots/deltas, and revision leasing | Durable SQLite catalog and operator publication CLI, co-located with Purr in the lab |
| **Aurora** | Future execution worker | Not part of the WordPress Child dependency chain; not integrated |

The user interacts with Purr Assistant, whose chat is powered by Purr. Products advertise active capabilities and product-owned evidence through `purrfect/product_signals`; inactive products are excluded. Purr provides guidance, not arbitrary product execution. Product-bundled knowledge remains fallback; a compatible, validated last-good Sophia lease takes precedence. Sophia's unavailability does not invalidate cached guidance.

Knowledge is approved by a trusted operator through the CLI; the `--approved` flag **is not** an authenticated human approval workflow. Product knowledge and Sophia package revisions are separate: knowledge entries can carry individual `Revision N` metadata and change notes. Source identifiers are formatted for display, while stored original sources remain stable.

## Foundation milestone — Goals 1.1–1.12

**Foundation prototype implemented; production readiness not claimed.** [PR #3](https://github.com/gnznovus/project-purrfect-4.0/pull/3) (Goal 1.11) and [PR #4](https://github.com/gnznovus/project-purrfect-4.0/pull/4) (Goal 1.12) are merged. Main-branch CI passed after integration ([run](https://github.com/gnznovus/project-purrfect-4.0/actions/runs/39120678187)).

Goal 1.11: The WordPress-facing names are **Purr Assistant**, **Purr**, and **Sophia**, while technical identifiers retain their existing spellings. Accepted UI includes the P2 sidebar/health icon and the U2 open/closed-eye header illustration. Hover closes Purr's eyes; automatic blinking respects the browser's `prefers-reduced-motion` preference. Automated blinking with reduced motion disabled was not separately observed in browser acceptance. Other responsive and accessibility combinations remain unexhaustively tested.

Goal 1.12: A repeatable Windows Docker bootstrap was implemented and merged. It checks Docker, starts the lab, provisions Ollama `llama3.2:3b` with retries, tests real inference, initializes **empty** Sophia demo knowledge, and installs/activates a **new** WordPress lab. CI checks the PowerShell parser and existing suites but **does not run a complete clean-laptop bootstrap**. Fresh-machine end-to-end acceptance, including a second run that preserves state, remains pending.

For a concise milestone inventory and limitations, see [Foundation status](docs/FOUNDATION-STATUS.md).

## Fresh Windows clone — Goal 1.12 bootstrap

Requires Git, Docker Desktop with Linux containers, network access for Docker images/Ollama model downloads, and available local ports (8084 for Site A; 8083 if Site B is enabled). A dedicated GPU is **not required**; CPU inference is slower. This is a local lab, not a production deployment.

From a new checkout:

```powershell
git clone https://github.com/gnznovus/project-purrfect-4.0.git
cd project-purrfect-4.0
.\bootstrap.ps1
```

Setup brings up Site A, Ollama, Purr and Sophia, downloads the `llama3.2:3b` model if needed, verifies a real Ollama response, seeds only an **empty** Sophia lab catalog with the approved **mock/demo fixtures**, installs WordPress interactively on first run, activates the example products, and waits for the existing heartbeat. Follow the password prompt for the local WordPress admin account. The same command can be rerun without deleting volumes or recreating accounts.

Use `.\bootstrap.ps1 -SiteB` to provision both independent WordPress sites. On failure, read the console diagnostic and rerun; never reset volumes to recover. A model download may take time and inference on CPU may be slower. The script exits with an error if inference or initialization fails; it does not silently claim a working Brain. WordPress state and the Sophia catalog are local to each laptop and are not cloned from another machine. To develop/test Python directly outside Docker, install Python 3.14 as described below.

The bootstrap defaults Purr to Ollama mode for lab containers it starts; it does not install Ollama on Windows or expose the internal `purra:8765` port. Do not run the script on a shared production WordPress instance.

## Development and tests

From the repository root (PowerShell, Python 3.14 installed):

```powershell
py -3.14 -m pip install -e ".[dev]"
py -3.14 -m pytest
```

CI also runs PHP syntax/smoke checks, JavaScript syntax checks, and Docker Compose configuration checks. The latest pre-merge integration CI passed **147 Python tests**, PHP tests, and JS/Compose validation. See [PR #1](https://github.com/gnznovus/project-purrfect-4.0/pull/1) for integration evidence. Keep future acceptance reports tied to the tested commit rather than treating this number as a permanent guarantee.

The `stateful_*`, adaptive routing, and LangGraph paths include experiments and comparison tests; they are **not** proof of complete live support-task persistence or production LLM behavior.

## Existing WordPress lab

The repository contains an additive two-site Docker Compose lab:

| Site | URL | Local state |
| --- | --- | --- |
| Site A | http://localhost:8084/wp-admin/ | Own WordPress database, registry, leases, heartbeat |
| Site B | http://localhost:8083/wp-admin/ | Independent WordPress database, registry, leases, heartbeat |

Both sites use the same lab Purr/Sophia service container and Sophia data volume. Port `8085` is **reserved for Syndacast Layout Engine**, not this lab.

For an **already installed** lab, run from repository root:

```powershell
$compose = @(
  '-f', 'wordpress/lab/compose.yaml',
  '-f', 'wordpress/lab/compose.site-b.yaml'
)
docker compose @compose --profile brain up -d --no-recreate db wp clock db_b wp_b clock_b purra
docker compose @compose ps
```

Do **not** rerun WordPress installation on existing sites. On a new lab, use the WordPress installer and activate **Purr Assistant**, **Purr Mock Layout**, and/or **Purr Mock Translation** through each site's Plugins screen. See [Site B setup and acceptance](wordpress/lab/SITE-B-ACCEPTANCE.md).

The WordPress admin **Purr Assistant → Control Center** offers:
- **Registry:** version checking through WordPress native update data; `Update All` uses native upgraders on registered products only.
- **Knowledge:** expandable Product → Category → Entry tree; read-only `Check Versions`, approved `Update All` synchronization, individual entry revisions and compatibility checks.
- **Settings:** plugin version, diagnostic bootstrap SHA-256 (not verified release integrity), heartbeat history, and independent Purr Assistant/Purr/Sophia health.

Knowledge controls pause while Sophia is unavailable; the heartbeat and open admin page detect recovery and automatically refresh read-only version statuses. The floating **Purr** chat widget remains on administrator pages. The chatbox is branded **Purr Assistant**, while messages are spoken by **Purr**. The former full-page **Local Bridge Lab** UI was removed.

Without the bootstrap, the default local Brain mode is deterministic. The Goal 1.12 bootstrap selects Ollama mode for the containers it starts. Ollama routing is otherwise optional (`PURRA_BRAIN_MODE=ollama` with a reachable, provisioned Ollama service); it must be validated separately.

### Safety and operations

- Do **not** run `docker compose down -v`, `docker volume rm`, or reset either WordPress or Sophia volume during routine operations.
- Internal `purra:8765` endpoints are intended only for the isolated lab. No cross-host authenticated deployment contract exists; never publish these endpoints to the internet.
- WordPress discovery and management endpoints require administrator permissions; chat and admin AJAX use nonce/capability checks.
- Cached leases are checksum validated. Health checks distinguish service availability from data integrity; a local bootstrap-file hash is **not** official release verification.
- The WordPress lab uses an external minute clock, with a WP-Cron fallback outside the lab. Component schedules are independent; manual checks use the same heartbeat dispatcher.
- The mock products are fixtures. A successful no-op native update check does **not** prove installing a real plugin release.

## Further work, not yet implemented

- Harden independent Sophia/Purr service authentication and deployment contracts.
- Validate actual plugin update packages and safe release integrity; rollback requires separately verified artifacts and recovery behavior.
- Implement a real proposal/review/approval workflow for shared knowledge rather than relying solely on operator assertion.
- Extend integrations beyond local mock products; test actual model behavior and persistence under real workloads.

**Working principle:** Build and validate focused slices first; document the proven state, unresolved boundaries and exact reproducible acceptance paths afterward. Avoid treating experimental code or green unit tests as production certification.
