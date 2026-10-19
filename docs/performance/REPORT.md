# Chat latency investigation â€” 19 October 2026

**The local HTTP service meets the measured warm latency target. Full acceptance is NOT met.** Language and routing errors remain, and authenticated browser â†’ WordPress AJAX â†’ Purr latency was not measured. Routing-contract checks below do not establish semantic correctness or preservation of personality.

Work started at `d01b741a45eb9d0ca65f3db4c178880baca0ed3c` on `feat/unified-intent-langgraph`. Changes are on `feat/chat-latency-optimization`. No PR or merge. All artifacts and code changes are inside this repository. No model downloads, paid inference, new dependencies, or permanent host configuration changes were needed. A repository-local virtual environment installed the existing declared development dependencies.

## Measured results

| Implementation | Normal warm samples | p50 ms | p95 ms | Under 5,000 ms | Routing-contract checks |
|---|---:|---:|---:|---:|---:|
| Baseline | 40 | 8,287.61 | 15,465.33 | 4/40 | 21/40 |
| Retained implementation, two rounds | 80 | 1,899.42 | 2,538.18 | 80/80 | 78/80 |
| Fresh validation corpus | 27 | 1,961.93 | 3,137.82 | 27/27 | 26/27 |

The primary p95 fell by approximately 84%. The primary corpus is identical between baseline and retained implementation: SHA-256 `d1bf9fda14812032df6fca51754d441ecf36306e3bcd13be815e4dde5b104085`. The first warm round has 40 different messages, including social chat, severe typos, vague assistance, product questions, WordPress, context, corrections, success, negation and troubleshooting. The second round repeats that corpus; it is not 80 unique messages. The 27 additional messages were frozen before their first run and were not used for prompt tuning of the retained implementation. They include a longer request.

Six additional boundary cases are excluded from *normal latency percentiles*, but retained in every report: invented capabilities, unrelated requests, instruction injection, forged buttons, stale workflows, inactive products. Failed normal requests remain included in latency statistics. Percentiles use nearest rank, `ceil(n*p)`. This is a small development sample, not a statistical guarantee for all traffic.

Cold-model samples, separate from all warm percentiles:

| Implementation | HTTP latency ms | Ollama model load ms |
|---|---:|---:|
| Baseline | 11,350.24 | 2,554 |
| Retained | 9,005.22 | 2,558.15 |

Cold means the selected model was explicitly unloaded through Ollama before the sample. It does not mean rebooted hardware or an empty OS filesystem cache. Both the graph's first use and the initial prompt computation are included. Warm model load p50 was approximately 1 ms; the existing 30-minute keep-alive was retained.

## Environment and measurement boundary

The same existing `lab-purra-1` container, `lab-ollama-1` service, CPU execution, model digest, context size and sequential client were used for the primary comparison. Benchmark runs did not overlap other inference benchmarks.

- Ryzen 5 230: six physical cores, twelve logical processors; 14,674,452,480 bytes host RAM, approximately 13.7 GiB.
- Docker Desktop: twelve CPUs exposed, 6,207,217,664 bytes memory, approximately 5.8 GiB.
- Radeon 760M integrated graphics, driver `32.0.22024.13003`, Windows reports 2 GiB dedicated VRAM.
- Docker Ollama `0.40.6`, `llama3.2:3b`, 3.2B `Q4_K_M`, digest `a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72`, context 2048. `/api/ps` reported zero VRAM allocation; `ollama ps` reported **100% CPU**.
- Container Python `3.14.8`, httpx `0.28.1`, LangGraph `1.2.16`, SQLite checkpoint adapter `3.1.2`.

The harness starts the **production `serve()` HTTP handler** on an isolated loopback port inside the existing Purr container. Client timing includes JSON encoding, HTTP round trip, handler processing, discovery, lease handling, state, LangGraph, Ollama, evidence retrieval and response decoding. It observes *every* adapter call, including fallback calls invisible to the old debug trace. It has no response memoization, route overrides or prompt-specific application behavior.

The synthetic inventory supplies registered, versioned fixture evidence and a real troubleshooting contract. It isolates benchmark sessions from live sessions and does not change Sophia's database. It does **not** measure browser rendering, WordPress login/nonce handling, PHP request transport, heartbeat/knowledge refresh, a large live Sophia catalog, concurrency or external network latency. Existing leases are still processed by the production handler; this fixture does not exercise a live lease refresh. No authenticated WordPress session was created or permission check bypassed to obtain a performance number.

Raw source fingerprints are recorded at startup in subsequent reports. Final Python source fingerprints match `optimized.json` exactly. The initial baseline ran the starting commit's code, loaded before edits; its older report lacks startup source fingerprints. The ignored `.benchmark-baseline` worktree preserves that commit for reproduction.

## What changed and why

1. **One inference attempt per free-text request.** Invalid JSON, unregistered IDs, unsafe wording, truncation and model/adapter exceptions terminate in safe clarification or existing deterministic feedback handling. They never enter another scope classifier or conversational generator. Older `TextModel.complete(system, user)` signatures are adapted *before* invocation; an internal `TypeError` is never retried. Explicit selections and exact troubleshooting confirmations still require zero model calls.
2. **Smaller, constrained generation.** Ollama receives a JSON schema for `route` and `response`. Registered product routes are derived from the current catalog. Support routes require a null response; verified server evidence supplies instructions. Social/help/clarification retain generated Purr wording. Server code builds canonical choices from current registered IDs and still validates proposals from older adapters. The unified generation budget is 80 tokens, rather than the adapter's general default of 160. Truncation is rejected. Schema structure is not a semantic safety guarantee.
3. **Shorter instructions and stable prefix ordering.** The unified prompt uses a concise statement of Purr's voice and scope rules. Stable registry/context precede the variable message. Existing Ollama KV prefix reuse avoids recomputing common text; no completed replies or intent decisions are cached. The shared full voice remains available to the other conversational helpers. Natural wording and correct conversational acts are still imperfect, as documented below.
4. **State and evidence guards.** Social turns and clarification retain topic, scope, outcome, evidence and active troubleshooting. In-memory scope is revalidated against fresh discovery. Product corrections and validated scope selections clear an incompatible workflow. A model alone cannot resolve an issue; existing success/negation heuristics and workflow guards remain. A product identifier alone no longer qualifies unrelated evidence within that selected product. These guards do not prevent a model from choosing the wrong *registered* product.
5. **`--debug` retained and extended.** It reports discovery/knowledge time, session-lock wait, graph time, model-call count, Ollama load/prompt/generation counters, token rates, transport overhead, output length, stop reason, validation rejections and error class. Raw model text and prompts are not included in diagnostics or browser context. Widget script version was bumped so browsers reload the diagnostic renderer.

Per normal request, summing all calls before computing percentiles:

| Cost | Baseline p50 | Retained p50 |
|---|---:|---:|
| Prompt processing ms | 956 | 234.41 |
| Generation ms | 6,801 | 1,643.38 |
| Generated tokens | 73 | 19 |
| Maximum model calls, all cases | 3 | 1 |

For example, baseline `Hii Purrr!!` took 10,369 ms and three calls. A quoted `"null"` target was rejected, another classifier returned an invalid kind, and the scope classifier finally returned `other`. A baseline WordPress password request generated 138 tokens, including unsupported instructions and invalid button IDs, before a second call selected WordPress. Generation and duplicate calls dominated; connection reuse or a new service would not address the main cost.

`prefix-reuse.txt` records runner messages such as `cached n_tokens = 450`, with only thirteen new tokens processed on one varied request. Reported `prompt_eval_count` and derived prompt throughput can include reused tokens; use the measured durations and runner cache logs when interpreting effective throughput. Output throughput was roughly eleven tokens/sec on this CPU.

## Alternatives measured

These are complete runs, with failures retained in the adjacent JSON files. Multiple prompt/schema changes were bundled per candidate, so the table does not isolate each change's causal contribution.

| Candidate | p95 ms | Normal routing-contract checks | Decision |
|---|---:|---:|---|
| Basic structured output | 3,721.70 | 26/40 | Rejected for routing errors |
| Target-first conditional schema | 5,004.34 | 32/40 | Rejected; redundant target/intent decisions persisted |
| Compact route with longer voice | 3,588.90 | 35/40 | Replaced by shorter prompt |
| Concise prompt, temperature 0.4 | 2,519.59 | 39/40 | Further constrained product scope; confirmed at temperature 0 |
| Retained compact confirmation | 2,538.18 | 78/80 | Smallest retained implementation |
| Brief paraphrase before route | 3,435.69 | 37/40 | Discarded: slower, no overall correctness gain |

The paraphrase experiment also produced awkward or incorrect social wording despite valid JSON. Its code was removed; its evidence is retained in `candidate-meaning.json`. No extra response cache, response template dictionary, greeting dictionary, semantic cache, paid model or new service was introduced.

## Acceleration verified

The installed native Windows Ollama `0.40.4` includes Vulkan. Its normal startup log says it skips the integrated GPU unless `OLLAMA_IGPU_ENABLE=1` is set. A dedicated **temporary localhost-only** process with that flag offloaded all 2,324,021,902 model bytes to GPU, as recorded by `/api/ps`. It used the already installed identical model digest.

The three-call hardware probe measured 7,962 ms including a 5,005 ms cold load, then warm calls of 1,845 and 1,203 ms. Generation throughput was 18â€“19 tokens/sec. It used the retained compact prompt, but is **not** a representative p95 benchmark or a same-environment CPU/GPU comparison: platform, Ollama version and sample inputs differ. It was not adopted as the default deployment. The probe unloaded its model and stopped only its own process; the pre-existing Windows service and host settings were unchanged. All probe logs are inside this repository and ignored by Git.

Ollama documents [schema-constrained output](https://docs.ollama.com/capabilities/structured-outputs) and [Vulkan hardware support](https://docs.ollama.com/gpu). Actual offload above is supported by the local measurements, not inferred from a graphics-card name.

## Correctness failures and acceptance limits

**Do not treat `correct_normal_n` as NLU accuracy.** It is the historical field name for routing/status/context assertions. Manual review found failures those assertions do not capture:

- `I have no idea where to begin with this site.` was classified as social in both confirmation rounds, returning `Hi there! How can I help you today?` instead of recognizing the lost user's request.
- `Hii Purrr!!` had the social route but returned `You're welcome! How can I make your day better?` A greeting was misinterpreted as thanks. The structural test passed; typo understanding was not preserved adequately.
- `i ned sme hlp pls` reached help, but `You need some help, okay?` falls short of the intended warm, useful voice.
- Some negated followups replayed existing product evidence instead of acknowledging failed guidance. They were not falsely marked resolved, but this is still a contextual-understanding failure.
- Fresh `Why are we doing this check?` reached the help/topic-selection path instead of explaining the current step. The active workflow and its attempt history were preserved.
- In one boundary sample, an invented-capability request naming `mock-layout` was routed to registered `mock-translation` and received its literal evidence. This is a wrong-product answer, despite the evidence being real.
- Both instruction-injection samples were routed to WordPress and returned irrelevant existing FAQ text. They did not publish, approve, execute or return the demanded `DONE`, but they failed the expected clarification contract. Broad lexical retrieval also allowed generic words such as `site` to match several FAQ entries.

Primary confirmation has five failed routing-contract samples overall: two normal samples plus three boundary samples. The validation corpus adds one failed workflow sample. Invalid classifier outputs are independently covered by automated tests and never cause another inference attempt.

Automated tests prove the covered state, evidence and permission contracts, not general natural-language reliability. **The no-loss language/personality requirement and complete end-to-end acceptance remain unproven and have known counterexamples.** The service's speed target alone is supported by the measurements. There is no claim of production acceptance.

Remaining work is semantic reliability and retrieval relevance, authenticated browser/WordPress timing, realistic Sophia catalog sizes, and concurrent traffic. The existing global session mutex spans inference and can serialize independent requests; Ollama CPU generation also limits throughput. Cold start remains above five seconds. GPU acceleration is available for further controlled evaluation, but does not itself fix interpretation errors. Further prompt tinkering without an independent semantic evaluation would risk optimizing these fixtures rather than general behavior.

## Regression results

- Starting code with the declared dependencies: **166 passed, 2 failed**. The two existing conversation failures concerned loss of scope on social chat and an obsolete conversational-model test stub. Initial system Python lacked the package path and LangGraph; the repository-local virtual environment resolved test collection without changing runtime dependencies.
- Final automated suite: **218 passed**. Existing model doubles were migrated from the old scope/drafting protocol to valid unified proposals while retaining behavioral assertions. New coverage checks malformed/untrusted output, truncation, adapter errors including internal `TypeError`, one-call budgets, zero-call buttons, retained workflows/evidence, revocation, negation and compact route validation.
- Existing PHP discovery, heartbeat, knowledge leasing, admin and network-health smoke tests passed using the existing lab PHP image with a read-only repository mount.
- JavaScript syntax checks, PowerShell parser checks, both Compose configurations and `git diff --check` passed.
- The existing local Purr container was reloaded after the final benchmark. A real HTTP smoke request returned current registered evidence in 2,538.42 ms with exactly one model call and the expanded debug counters; see `runtime-smoke.json`. This is an isolated service check, not authenticated browser acceptance.
- No live Sophia outage, authenticated WordPress session or production deployment acceptance was performed in this task.

## Exact local verification commands

Run from PowerShell in this checkout. Docker Desktop and the existing lab containers must be running. `--cold` deliberately unloads the selected local model before its separate cold sample.

```powershell
Set-Location C:\Code\Python\project-purrfect-4.0

# Only needed if the ignored local environment does not already exist:
python -m venv .venv
.\.venv\Scripts\python -m pip install --no-cache-dir -e '.[dev]'

.\.venv\Scripts\python -m pytest -q
node --check wordpress/purr-child/assets/chat.js
node --check wordpress/purr-child/assets/widget.js
node --check wordpress/purr-child/assets/admin.js
docker compose -f wordpress/lab/compose.yaml config --quiet
docker compose -f wordpress/lab/compose.yaml -f wordpress/lab/compose.site-b.yaml config --quiet

# Preserve baseline code inside the repository, without switching the working branch:
if (-not (Test-Path .benchmark-baseline)) {
    git worktree add --detach .benchmark-baseline d01b741a45eb9d0ca65f3db4c178880baca0ed3c
}
.\benchmarks\run.ps1 -Label baseline-recheck -SourcePath /workspace/.benchmark-baseline/src -Cold
.\benchmarks\run.ps1 -Label optimized-recheck -Cold -Rounds 2
.\benchmarks\run.ps1 -Label validation-recheck -Corpus holdout.json

# Recompute tables/CSV for the committed original measurements:
.\.venv\Scripts\python benchmarks/analyze.py

# Confirm the runtime's actual processor allocation after loading a model:
docker exec lab-ollama-1 ollama ps

# Optional isolated hardware probe; restores its environment and stops its server:
.\benchmarks\probe_acceleration.ps1

# Load checked-out code into the existing local Purr service:
docker restart lab-purra-1
```

PHP smoke commands, using only the already installed lab image:

```powershell
$repoPath = (Get-Location).Path
foreach ($test in @('test_discovery.php','test_heartbeat.php','test_knowledge_leasing.php','test_admin.php','test_network_health.php')) {
    docker run --rm --network none --entrypoint php --mount "type=bind,source=$repoPath,target=/workspace,readonly" lab-wp "/workspace/tests/php/$test"
    if ($LASTEXITCODE -ne 0) { throw "PHP test failed: $test" }
}

$tokens = $null
$parseErrors = $null
foreach ($script in @('bootstrap.ps1','benchmarks/run.ps1','benchmarks/probe_acceleration.ps1')) {
    [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $script), [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -gt 0) { throw "PowerShell parse failed: $script" }
}
git diff --check
```

Raw reports contain requests, responses, every adapter call and timing counters. `samples.csv` keeps all cases, including failures and boundaries. `comparison.json`, `hardware.json`, `native-acceleration.json`, `prefix-reuse.txt` and `regressions.txt` provide supporting evidence. `semantic-audit.json` identifies counterexamples from the archived confirmation runs before the final scope guard; those raw runs are also retained. The benchmark runner prints summary statistics and writes its report under `docs/performance/<label>.json`; it never changes the production route based on the label or test input.

A successful benchmark process exit means a complete measurement report was saved. It does not mean the acceptance criteria passed; inspect the failure records and semantic review above.
