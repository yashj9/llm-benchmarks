# Third-party sources, attribution and licence audit

Audit date: 2026-10-13. Our original code is MIT; our original published results compilation/annotations are CC BY 4.0 **only to the extent we hold applicable rights**. Those declarations do not relicense benchmark assets, dependencies, model weights, third-party outputs, brands or unprotected facts.

**This is not an all-clear certificate for redistributing every benchmark dataset.** The public benchmark repository contains scores, numerical measurements and source credits—not benchmark statements, hidden tests, screenshots, reference answers or generated answers. Preserve that boundary. We have not contacted licensors or obtained permissions beyond the recorded licences.

## Sources used in preserved Quality runs

### Original coding and tools/MCP tasks

Credit: **YashJ / Quality project contributors**. Original task wording, local fixtures/world and grading code are covered by our MIT declaration. The MCP suite uses the MIT-licensed [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk); credit **Anthropic, PBC and MCP contributors** and retain the upstream [full licence notice](licenses/third-party/mcp-mit.txt).[5] Protocol implementation is external; our custom tasks are not an Anthropic benchmark.

### EvalScope — framework, Apache-2.0

Credit: **Alibaba ModelScope / ModelScope Team and contributors**. [Project](https://github.com/modelscope/evalscope) · [upstream licence](https://github.com/modelscope/evalscope/blob/main/LICENSE) · [preserved full text](licenses/third-party/evalscope-apache.txt).[4]

Used for legacy benchmark evaluation and native SimpleQA grading. Local wrappers/custom suites and a bounded sample do not claim to reproduce an official full benchmark score. Apache-2.0 applies to the framework, **not automatically to every dataset it downloads**. The environment remains separate; we do not redistribute its binaries or claim to have reviewed every transitive dependency. Preserve installed dependency notices; perform a separate dependency/distribution review before packaging an environment.

### GSM8K — OpenAI, MIT

Credit: **OpenAI; Karl Cobbe and collaborators**, *Training Verifiers to Solve Math Word Problems*. [Original dataset repository](https://github.com/openai/grade-school-math) · [upstream MIT licence](https://github.com/openai/grade-school-math/blob/master/LICENSE) · [preserved notice](licenses/third-party/gsm8k-mit.txt).[1]

Our retained main/test cases were used as a zero-shot, numeric-accuracy bounded sample. This is not the official published benchmark protocol. The original repository includes dataset files under its MIT licence; keep OpenAI copyright/licence notices with copied material. The public site exports scores, not question/answer text.

### SimpleQA — OpenAI; code MIT, mirrored data terms not separately cleared

Credit: **OpenAI / SimpleQA authors**, *Measuring short-form factuality in large language models*. [Original evaluation repository](https://github.com/openai/simple-evals) · [upstream code licence](https://github.com/openai/simple-evals/blob/main/LICENSE) · [preserved notice](licenses/third-party/simpleqa-mit.txt).[2]

Our historical bounded factuality sample used a locally cached dataset mirror with the native EvalScope two-pass rubric. The simple-evals repository licence is verified MIT. We have **not independently established licence coverage for every externally hosted CSV and the exact retained dataset mirror**. Do not redistribute those assets under our licences without checking that provenance. Score-only reporting does not purport to grant rights over the source assets.

### LiveCodeBench — credit benchmark authors and original contest platforms

Credit: **LiveCodeBench authors** (*LiveCodeBench: Holistic and Contamination Free Evaluation of Large Language Models for Code*) and **AtCoder / LeetCode problem authors and contributors**. [Project](https://github.com/LiveCodeBench/LiveCodeBench) · [dataset](https://huggingface.co/datasets/livecodebench/code_generation_lite) · [AtCoder](https://atcoder.jp/) · [LeetCode](https://leetcode.com/).

The runner repository is MIT: [upstream licence](https://github.com/LiveCodeBench/LiveCodeBench/blob/main/LICENSE), [preserved notice](licenses/third-party/livecodebench-code-mit.txt).[3] That is **not proof that all contest statements and hidden tests have an unrestricted dataset grant**. Available dataset-card evidence uses an imprecise `cc` label; a historical loader also says MIT. A complete, precise licence for the exact retained test6 data and underlying contest rights was not established. **Unrestricted asset redistribution is not cleared.**

Local modifications: 24 selected hard contest problems, custom hard/extreme tiers, exclusions for non-exact-output grading, deterministic hidden-test sampling and local Python exact-match grading; the lite profile retains 3 cases. These are curated local scores, not official LiveCodeBench leaderboard scores. Questions and test files are excluded from our MIT/CC BY grants and from the public benchmark snapshot.

### ArtifactsBench — real same-snapshot licence conflict

Credit: **Tencent Hunyuan Team and ArtifactsBench authors**, *ArtifactsBench: Bridging the Visual-Interactive Gap in LLM Code Generation Evaluation*. [Project](https://github.com/Tencent-Hunyuan/ArtifactsBenchmark) · [dataset](https://huggingface.co/datasets/tencent/ArtifactsBenchmark) · [paper](https://arxiv.org/abs/2507.04952).

Verified [current GitHub licence](https://github.com/Tencent-Hunyuan/ArtifactsBenchmark/blob/main/LICENSE), [preserved full text](licenses/third-party/artifacts-github-license.txt), says **CC BY 4.0**.[8] However the archived dataset downloaded at revision **40e5597429a127963ebd03130851e898fb8ba982** contains:

- `License.txt`: “ArtifactsBenchmark is licensed under the Creative Commons Attribution 4.0 International Public License (CC BY 4.0)”.
- `README.md` metadata: `license: cc-by-nc-4.0`.
- The saved download metadata pins both files and `artifacts_bench.json` to that same revision.

This is a real conflict, not permission to silently choose the more permissive reading. **Do not advertise unrestricted commercial use/redistribution of these prompts until the publisher clarifies.** Retain the assets privately and preserve their notices; any future unrestricted bundle should omit or independently replace these assets unless clarified. No permission inquiry has been posted automatically.

Local modifications: 12 selected prompts/checklists, locally written reference designs, custom tiers and manual 1–5 ratings; 3 retained lite cases. We do **not** use or claim the upstream automated multimodal-judge scoring protocol. Manual design ratings stay separate from the combined automatic quality score. Neither source prompts nor generated design artefacts are distributed by the public scores site.

## Retained adapter, not a preserved real public run

### ScreenSpot-v2 — publisher declares Apache-2.0; exact snapshot not verified

Credit: **OS-Copilot / ScreenSpot-v2 contributors** and original UI/application owners. [Dataset](https://huggingface.co/datasets/OS-Copilot/ScreenSpot-v2) · [publisher mirror](https://modelscope.cn/datasets/OS-Copilot/ScreenSpot-v2) · [Apache-2.0 legal text](licenses/third-party/apache-2.0.txt).[7]

The publisher's dataset listing declares Apache-2.0, consistent with our retained suite documentation. We did not retrieve the exact retained snapshot's dataset notice or verify all underlying screenshot/brand rights; current dataset endpoints failed during this audit. Do not treat the code licence as a blanket grant over screenshots. Local modifications: balanced platform/target/size sampling, bounding-box coordinate scaling and point-in-box scoring (108 full / 6 lite cases). The current public results contain no preserved real ScreenSpot run. Screenshots/annotations are not exported; unrestricted asset redistribution remains uncleared pending snapshot verification.

## What our licences require—and do not require

- **MIT code:** preserve copyright and licence notices when redistributing copies/substantial portions. It does not require a visible UI badge, a backlink on every derivative site, or credit for every private execution.
- **CC BY 4.0 original compilation/analysis:** appropriate attribution, a licence link and indication of changes when sharing protected licensed material. No added non-commercial, share-alike or field-of-use restrictions.[6]
- **Raw facts:** we do not manufacture exclusive rights over numerical facts or impose attribution where no relevant rights apply.
- **Upstream material:** preserve applicable copyright/licence/NOTICE files and modification notices. Never strip upstream notices or substitute our licence for theirs.
- **Unverified/conflicting assets:** exclude from an unrestricted public asset bundle until clarified. Crediting a source does not itself grant permission.

## Audit evidence and scope limits

`SOURCES.json` is the machine-readable source registry, including explicit verification states, licence URLs, upstream retrieved licence-body SHA-256 values and the ArtifactsBench revision. Full upstream licence texts are preserved with only line-ending/trailing-newline normalization. The exact dataset endpoints for LiveCodeBench, ArtifactsBench and ScreenSpot returned rate-limit/server errors; these failures are not represented as successful verification. Archived ArtifactsBench files and metadata provided the same-snapshot evidence above.

The audit covers sources used in preserved Quality runs, the retained ScreenSpot adapter, and the directly relevant EvalScope/MCP frameworks. Unused legacy benchmark downloads, model/runtimes (including LM Studio/Strata), and the full installed dependency environment are not claimed cleared. Model terms remain their own; no model weights or external benchmark assets are distributed here.

## Sources

[1] https://raw.githubusercontent.com/openai/grade-school-math/master/LICENSE
[2] https://raw.githubusercontent.com/openai/simple-evals/main/LICENSE
[3] https://raw.githubusercontent.com/LiveCodeBench/LiveCodeBench/main/LICENSE
[4] https://raw.githubusercontent.com/modelscope/evalscope/main/LICENSE
[5] https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/LICENSE
[6] https://creativecommons.org/licenses/by/4.0/legalcode.txt
[7] https://www.apache.org/licenses/LICENSE-2.0.txt
[8] https://raw.githubusercontent.com/Tencent-Hunyuan/ArtifactsBenchmark/main/LICENSE
