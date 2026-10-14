# Local LLM Benchmarks — Dyno + Quality

Public, static scores-only snapshot of local LLM benchmarking: the original RTX 5090 (32 GB) + RTX 5060 Ti (16 GB), 64 GB system-RAM platform, plus a separate AMD Strix Halo sequential-campaign leaderboard (Framework Desktop / Ryzen AI Max+ 395 / 128 GB unified memory).

**Website:** https://yashj9.github.io/llm-benchmarks/

## Views

- **Combined leaderboard:** the existing Quality arena calculations, with shared suite versions/case sets, per-protocol scores, 90% bootstrap intervals, separate design ratings and representative Dyno speed.
- **Speed by setup:** active finished Dyno sessions grouped by exact model, engine, context, thinking choice and recorded GPU placement. Every contributing session is linked.
- **Cold / hot prefill:** saved fresh-prefix / identical-repeat probes, prompt lengths and TTFT, with cache-verification caveats. General long-context prompt rates are shown separately.
- **System resources:** side-by-side RAM, per-GPU VRAM, CPU load/power, GPU power and temperatures; sort by lower memory/power and filter exact contexts. Dyno setup captures and Quality job captures are separate.
- **Dyno runs:** all preserved real sessions, including archived and failed attempts, with per-request scores/timing/token counts and recorded settings.
- **Quality runs:** all preserved real runs, including previous protocols, cancellations, historical benchmark suites and manual design tasks. Per-test scores are public; generated content is not.

The initial snapshot contains **57 Dyno sessions** (31 archived) and **120 Quality suite runs**. Six reference/synthetic smoke-test runs are excluded. These are suite-run counts, not 120 full model batteries. Missing settings remain unknown. Archives are visible in history but do not re-enter active rankings.

## Metric definitions

Quality is the tier-weighted pass rate over the auto-scored coding, tools/MCP and contest coding suites: easy/medium/hard/extreme weights 1/2/3/4. Standard protocol: thinking off, 8192 maximum output tokens, the shared 18 auto-scored lite cases. Three additional design cases require manual rating and are separate. Each non-standard protocol has its own leaderboard view; unrecorded or incompatible protocols remain history-only.

Dyno reliability is a different practical-task score, using scored/error requests with prompt size <=64K. Request errors are misses. Decode speed uses <=16K (short) and >=64K (long) prompt buckets. Each finished session is reduced first, then setup groups use medians over session medians with min/max spread. The combined arena chooses its representative speed setup using the local arena policy, not an unqualified "fastest ever" selection.

Balanced score is 70% quality + 30% log-normalized speed (10–100 tok/s, capped at 100). It is a preference score, not a universal ranking. Quality and speed typically come from different runs; engines, thinking and parallel settings can differ. Compare exact configurations in Details.

**Strata caveat:** the IQ2_XS Dyno sessions hit many small output-token caps. Their low reliability is budget-limited evidence, not the separate Quality score. Preserve both the misses and the warning. GPU mode "both" means both participated; it does not assert one universal device-order policy across engines.

## Prefill and resources

The saved paired probes cover **16 of 19 active Dyno setups**. Each probe sends a fresh randomized prefix then repeats that exact prompt. Their rates are the recorded **prompt tokens / client TTFT**, not native engine prompt-compute throughput. The repeat is an observed hot-prefix test, but **none of these pairs exposed verified cache hits**. The site marks cache evidence unverified instead of claiming verified cached-token processing rates. Prompt lengths span roughly 12K–13K tokens across tokenizers; this is the same 260-record workload, not an exact token-matched workload. Model-load cold start is a different metric. Strata has long-context rates but no saved dedicated pair, so its cold/hot pair values remain missing. General long prefill uses the original >=64K prompt bucket and is shown separately with mixed cache states.

Resource evidence covers **all 19 active Dyno setups** and **9 of 40 preserved Quality jobs**. Unmeasured Quality jobs remain visible as `Not recorded`. Quality job counts are distinct from suite-run counts (120). The eight measured LM Studio Quality jobs used thinking-on; the separate Strata Quality job used thinking-off. Do not compare them as equal generation workloads.

For each accepted Dyno run, timestamp-bounded post-load telemetry yields RAM mean/peak/minimum free memory, loaded-idle RAM, per-GPU VRAM peaks, CPU and GPU mean load/power, and sensor temperatures. Strata also exposes swap and disk I/O. Historical data with missing sensors is not filled with zero. Across repeated sessions, setup summaries use **median session means**, **maximum observed peaks**, and **minimum RAM headroom**. This is whole-system observation, not isolated model allocation. The loaded-idle snapshot is not an unloaded baseline. CPU+GPU power sums CPU package and the two NVIDIA devices only where all three are available at the same sample; it is **not wall power** and excludes other components. No watt-hours or energy-efficiency ranking is invented.

Quality resource rows use the exact managed job ID in the matrix log to link saved telemetry. These capture the complete job’s load/run/unload window and are never assigned per suite as isolated consumption. The resources selector keeps these separate from Dyno post-load workloads. Filter matching contexts/GPU configurations before comparing, and inspect session IDs, source/sensor coverage and generation controls in Details.

## Privacy and provenance

The exporter constructs a new allowlisted record, not a dump of source directories. No credentials, API endpoints, local paths, machine identifiers, raw prompts, generated responses, error text or private story drafts are published. Only scores, benchmark identities, known configuration controls and numerical performance measurements are exported. No benchmark is run by this website or by GitHub.

The input datasets remain local/private. The website has no access to the source machine, and no analytics or external scripts. Original Dyno and Quality repositories are not made public or modified by this project.

## Updating the snapshot

Use the Quality project's Python environment (the arena importer uses its dependencies):

```sh
python scripts/export.py --dyno /path/to/dyno --quality /path/to/quality-evals --matrix /path/to/lmstudio-matrix --out data/snapshot.json
python -m unittest discover -s tests -v
node tests/test_ui.cjs
node --check app.js
```

Set `BENCHMARK_WORKSPACE` to the parent of those repositories to run the optional read-only source integration test. That test's initial snapshot counts must be reviewed when genuine new runs are added. Export fails on disallowed content. Review the JSON diff, commit, and push `main`; GitHub Pages deploys the new static snapshot. No nightly job or inference worker is configured.

## AMD Strix Halo sequential campaigns (additive extension)

The `dyno_campaigns` extension adds **3 campaigns / 13 finished model reports**: 11 chat sessions (including the distinct Nail repeat) and 2 embedding-only reports. `campaign-001` contributes 11 reports, `campaign-002-nail-repeat` one, and `campaign-003-unsloth-q8kxl` one. All original snapshot fields, timestamps, counts, record identities and values remain unchanged: 57 original Dyno sessions, 120 Quality suite runs, 19 speed setups, and the original arenas/resources. The original summary cards explicitly refer to that original snapshot, not a fabricated combined total.

Use **Strix Halo campaigns** for the new speed leaderboard and its Details. Hardware / platform filtering composes with search, context and GPU-placement filters in every view. `legacy-snapshot` means membership in the original NVIDIA snapshot; no per-record hardware field is retroactively invented and unknown placements remain unknown. AMD results have an explicit `amd-strix-halo` platform. Selecting AMD in an original-only view correctly yields no matching results; there are no AMD Quality runs to merge into the combined arena.

This is intentionally a separate protocol, not a conversion into the old setup/reliability schema. The new battery mixes practical tasks and cache probes, includes thinking, and lacks comparable Quality scores. Speed-only results must not enter the Quality/balanced arena or inherit its reliability policy. Rows retain exact session IDs, campaign and attempt IDs, model tags/digests, configured/effective contexts, thinking selection, source code/fixture versions, source SHA-256 provenance, and coarse metadata plus separate GGUF tensor type evidence. Runtime version and MTP acceptance remain unmeasured; a model tag is not a verified quantization label.

Hardware: operator-supplied **Framework Desktop / AMD Ryzen AI Max+ 395 (Strix Halo) / 128 GB unified memory**. The source additionally records `AMD RYZEN AI MAX+ 395 w/ Radeon 8060S` and OS-visible memory (not installed memory). Do not reinterpret the small driver VRAM aperture or GTT mappings as dedicated VRAM/model allocation. Details expose selected numerical telemetry aggregates only; PPT package power is not wall power or the original CPU-plus-two-NVIDIA-GPUs metric. Foreign residency/eviction counts are comparison variables, not proof of concurrent inference.

### Reduction and validity

- Sustained speed is the median of successful raw requests with **at least 256 output tokens**, excluding calibration/warm-up/first-request probes. Output counts include thinking; stopped or token-capped generations can qualify as speed evidence, not answer-quality evidence. Request count, errors, excluded count, min/max and per-workload reductions remain available. One-token million-token/s calibration artifacts never enter rankings.
- Cold prefill uses **new tokens / native prompt-evaluation duration**, at the largest strictly valid uncached cache-probe size. It is not the original site's prompt/TTFT proxy. Fully cached replay is summarized by TTFT, not an inflated whole-prompt throughput. Depth is shown separately for cold and cached summaries; missing values stay missing.
- Every cache cell retains exact request ID, nominal depth, actual token counts, repetition, mode, fit, strict validity, TTFT and rates. Invalid uncached cells are disclosed but excluded from cold summaries; valid cached/partial cells and other sustained requests are still usable speed observations. Thus a finished battery is not automatically strict complete coverage.
- Nail's two runs retain **182 cached prefix tokens** on all 15 nominally uncached cells each; Qwen3.8 and Swift retain **42**. Llama3.2 also has strict-invalid uncached cells (15–23 reused tokens). No thresholds were loosened. `campaign-001` and Nail repeat retain `complete=false`; Unsloth campaign retains `complete=true`. Campaign 001 discloses three unselected/superseded attempts and its historical memory-headroom stop. Only ledger-selected finished reports are ranked; an old stop record is not the final campaign status.
- Embedding reports have no invented chat session ID or decoding/prefill speed. Batch-1/batch-8 median latency, all six measurements, dimensions and finite-vector validity are retained without input text or vectors.

### Reproduce the append-only import

No dependencies or source-runtime imports are needed. Source directories are read-only; no inference, service changes or uploads occur. `CAMPAIGN_ROOT` is the local directory containing the three campaign folders:

```sh
python scripts/import_campaigns.py --snapshot data/snapshot.json --out data/snapshot.json \
  --campaign "$CAMPAIGN_ROOT/campaign-001" \
  --campaign "$CAMPAIGN_ROOT/campaign-002-nail-repeat" \
  --campaign "$CAMPAIGN_ROOT/campaign-003-unsloth-q8kxl"
DYNO_CAMPAIGN_ROOT="$CAMPAIGN_ROOT" python -m unittest discover -s tests -v
node tests/test_ui.cjs
node --check app.js
node --check ui.js
```

Identical re-imports are idempotent; a changed existing campaign/run identity fails closed instead of overwriting it. Source pointers must stay inside the campaign/attempt. The exporter constructs an allowlist and scans the extension for private paths, endpoints and content fields; raw prompts, generated answers, vectors, logs and templates never enter the public extension. Existing `generated_at` remains the original snapshot date; run timestamps establish the new evidence dates. Do not run the original replacement exporter directly over the combined publication: export the original protocol to a separate staging file, preserve/reconcile existing records, then apply this additive importer after review.

Tests deeply compare every original top-level value/record against the git baseline, verify repeats/cache/embedding coverage, privacy and source-pointer guards, and (with `DYNO_CAMPAIGN_ROOT`) rebuild from the real sources, test idempotence and reject identity conflicts. Optional original-source integration tests still need the older private Quality/matrix datasets.

## Licensing and credit

Copyright (c) 2026 **YashJ**. Original website/exporter code is [MIT](LICENSE); our original scores compilation/annotations, to the extent applicable rights exist, is [CC BY 4.0](data/LICENSE). Third-party benchmark assets, upstream notice texts under `licenses/third-party/`, and unprotected facts are excluded. No non-commercial, share-alike or mandatory UI-branding condition is added.

Recommended data citation: **YashJ, Local LLM Benchmarks (Dyno + Quality), snapshot date recorded in `generated_at`, https://yashj9.github.io/llm-benchmarks/**. [CITATION.cff](CITATION.cff) supplies machine-readable credit. Sharing protected CC BY material requires appropriate attribution, a licence link and indication of changes; redistributing MIT code requires retaining copyright/licence notices. Neither licence invents a duty to credit every private execution or every reuse of an unprotected fact.

Every exported Quality run carries `source_ids`; the downloadable snapshot includes licence scope, author credit and the upstream source registry. The webpage keeps benchmark names as measurement provenance, without optional upstream credit cards or author-attribution panels. Required copyright/licence notices are retained in the repository; this presentation policy does not change the upstream terms or declare unresolved datasets cleared. Reassess webpage attribution if third-party code, questions, screenshots or other licensed assets are ever added to the site. Read [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [SOURCES.json](SOURCES.json) before copying external assets: some dataset grants are conflicting or unverified, and credit alone does not clear them. Only original measured scores/annotations are licensed here; no source benchmark questions, hidden tests, screenshots, raw responses or model weights are bundled.

## Hosting

GitHub Pages serves `main` at the repository root. `.nojekyll` disables Jekyll processing. No build dependencies are needed for the site; it consists of HTML, CSS, JavaScript and a JSON snapshot. For local browsing:

```sh
python -m http.server 8877 --bind 127.0.0.1
```

Then open http://127.0.0.1:8877/. Browser Details show only sanitized metrics. Download scores exports the same public snapshot.
