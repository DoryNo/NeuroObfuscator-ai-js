# NeuroObfuscator

Adaptive JavaScript obfuscation with a neural planner. A fine-tuned **Qwen2.5-Coder-7B** reads your
JavaScript plus its AST features and emits an **obfuscation plan** (JSON); a deterministic **Babel
engine** applies the plan; and every result is proven behavior-preserving by a **differential test**
on 50 argument sets before it is accepted.

## Model:

https://huggingface.co/doryno/NeuroObfuscator-ai

You control the result with a single knob — **target intensity** (`light` / `medium` / `heavy`) —
which the model was explicitly trained to obey in the *content* of the plan, not just in its label.

## Results (v7.1, 750 held-out test functions)

| Metric | v6 | **v7.1** |
|---|---|---|
| JSON parse rate | 100% | **100%** |
| Schema valid rate | 100% | **100%** |
| Semantic pass rate (apply + differential validation) | 100% | **100%** |
| Intensity obedience — field | n/a | **100%** |
| Intensity obedience — plan shape | n/a | **100%** |
| Light purity (light ⇒ rename + dead_code only) | 4.3% | **100%** |
| Unique transform orders | 8 | 10 |
| Top non-light order share | 62.3% | **19.0%** |

All metrics are measured on the exact deployable artifact (GGUF q8_0 through llama.cpp), and
semantic pass runs the real Babel engine with differential execution.

## How it works

```
                 ┌────────────────────────────────────────────────────────┐
 JavaScript ───▶ │ extract AST features (18 features: cyclomatic          │
                 │ complexity, string/op counts, nesting, try/catch, ...) │
                 └───────────────┬────────────────────────────────────────┘
                                 │  code + features + seed + target intensity
                                 ▼
                 ┌────────────────────────────────────────────────────────┐
                 │ Qwen2.5-Coder-7B (QLoRA fine-tune, GGUF)               │
                 │  → obfuscation plan JSON (no seed; runtime injects it) │
                 └───────────────┬────────────────────────────────────────┘
                                 │  plan: intensity, transforms{...}, order[...]
                                 ▼
                 ┌────────────────────────────────────────────────────────┐
                 │ Deterministic Babel engine (seed-controlled PRNG)      │
                 │  rename → string_encode → operator_sub →               │
                 │  dead_code → opaque_predicates                         │
                 └───────────────┬────────────────────────────────────────┘
                                 │  obfuscated code
                                 ▼
                 ┌────────────────────────────────────────────────────────┐
                 │ Differential validation (node:vm, 50 argument sets,    │
                 │ timeout): original vs obfuscated must match exactly    │
                 └────────────────────────────────────────────────────────┘
```

### Intensity semantics (learned from data, enforced by gates)

| Target intensity | Plan shape |
|---|---|
| `light` | `rename` + `dead_code` only |
| `medium` | 2–4 transforms, `string_encode`/`operator_sub` when applicable, **no** `opaque_predicates` |
| `heavy` | all relevant transforms, **always includes** `opaque_predicates` |

### Plan format

The model outputs only the JSON body (seed is injected by the runtime, never predicted):

```json
{
  "intensity": "heavy",
  "transforms": {
    "rename": {"enabled": true, "keep": []},
    "string_encode": {"enabled": true, "method": "charcode_array", "min_length": 2},
    "operator_sub": {"enabled": true, "rate": 0.95},
    "dead_code": {"enabled": true, "count": 2},
    "opaque_predicates": {"enabled": true, "count": 3}
  },
  "order": ["rename", "string_encode", "operator_sub", "dead_code", "opaque_predicates"]
}
```

## Quickstart

Requirements: **Node.js 20+**, **Python 3.11+**.

```powershell
git clone <this-repo>
cd neuroobfuscator
npm install          # Babel engine dependencies
npm test             # 13 engine unit tests
npm run smoke        # end-to-end dataset pipeline smoke test
```

### Run the engine directly

```powershell
node engine/index.js --input input.js --plan plan.json --output obfuscated.js

# JSON API (used by all Python tooling):
'{"operation":"extract_features","code":"function f(x){if(x)return 1;return 0;}"}' | node engine/index.js --json
```

Engine operations: `extract_features`, `apply`, `validate` — all seed-deterministic: the same
plan + seed always produce byte-identical output.

### Run the demo UI

```powershell
npm run demo         # Gradio app on http://127.0.0.1:7860
```

The app works out of the box in **heuristic fallback mode** (deterministic, feature-driven plans).
To enable the neural planner, put the model weights somewhere findable:

- set `NEURO_GGUF=/path/to/model.gguf`, or
- drop a `*.gguf` file into `models/`

Weights are not redistributed with the repo — produce them yourself with the training notebook
(see below), which exports a GGUF with the LoRA merged.

## Dataset pipeline

Synthetic + real (MIT/Apache-licensed GitHub repos) JavaScript functions are filtered, featured,
planned, executed, validated, scored and stratified into splits with hard acceptance gates.

```powershell
python scripts/00_generate_synthetic.py --count 10000 --seed 2026 --modern-share 0.25 --output data/raw
python scripts/01_collect.py --source "E:\path\to\javascript" --output data/raw
python scripts/01_collect.py --git-url https://github.com/<org>/<repo> --output data/raw
python scripts/02_filter.py
python scripts/03_extract_features.py
python scripts/04_generate_plans.py --plans-per-function 6 --adaptive --intensity-seeded
python scripts/05_apply_and_validate.py
python scripts/06_score_and_select.py --drop-contradictions --conditional-shapes \
    --allow-multi-intensity --max-order-share 0.14 \
    --intensity-targets "light=20,medium=45,heavy=35"
python scripts/07_format_for_training.py --conditional
python scripts/08_split_dataset.py --seed 2026
python scripts/09_audit_dataset.py --enforce
python scripts/12_build_dpo.py --conditional --drop-contradictions
```

Or run the whole v7 build with one command: `scripts/run_v7.sh`.

**Dataset v7.1 (conditional):**

| Artifact | Records |
|---|---:|
| Validated candidate plans | 103,580 (from 139,920 generated) |
| Selected SFT records | 7,500 (900 real + 6,600 synthetic) |
| train / val / test | 6,000 / 750 / 750 (real: 720 / 90 / 90) |
| Multi-intensity contrast functions | 1,152 (every intensity variant has a *different* order) |
| DPO preference pairs | 19,937 |
| Label contradictions (R1–R6 audit) | **0** |
| Cross-split function leakage | **0** |

## Training

Google Colab notebooks (Unsloth + QLoRA on T4/L4/A100):

- `colab_train_v7,1.ipynb` — SFT: Qwen2.5-Coder-7B-Instruct 4-bit, LoRA `r=32, alpha=64`,
  lr `2e-4`, 3 epochs, cosine, effective batch 16, loss on the JSON completion only
  (prompt tokens are masked). Exports LoRA adapter + merged GGUF (q4_k_m / q8_0).
- `colab_inference_v7.ipynb` — evaluation of the exported GGUF through llama.cpp:
  parse/schema rates, field & shape obedience, light purity, diversity, and the
  **semantic pass rate** (every plan applied and differentially validated by the real engine).
- A DPO stage on `dpo_pairs_v7.jsonl` is prepared for the next iteration (within-intensity
  diversity).

## Evaluation report (v7.1)

```
- Test set: 750 records (conditional)
- JSON parse rate:  100.0%   (target >= 95%)
- Schema valid rate: 100.0%  (target >= 90%)
- Field obedience:  100.0%   Shape obedience: 100.0%
- Light purity:     100.0%
- Semantic pass rate: 100.0%
- Unique orders: 10 | top non-light order 19.0%
```

Per intensity: light 112/112, medium 355/355, heavy 283/283 — 100% each.

## Repository structure

```
engine/                 Babel transform engine (Node.js)
  plan.js               plan schema, normalization, canonical order
  random.js             seed-deterministic PRNG
  transforms/           rename, string_encode, operator_sub, dead_code, opaque_predicates
  apply_plan.js         parse → transform chain → generate
  extract_functions.js  standalone function extraction
  extract_features.js   18 AST features
  test_runner.js        differential execution (node:vm + timeout)
  index.js              JSON CLI (--json) and file CLI
scripts/                dataset pipeline 00–15, audits, DPO, evaluation, inference wrapper
app/main.py             Gradio demo (neural / plan-JSON / manual modes)
colab_train_v7,1.ipynb  SFT training notebook
colab_inference_v7.ipynb evaluation notebook (GGUF + engine)
tests/                  engine unit tests (npm test)
```

## Correctness guarantees

- The model only *plans*; the engine *mutates the AST* — no model output ever touches code directly.
- Plans are validated against a strict schema and the canonical transform order before any edit.
- One failed transform aborts the whole application — partial results are never returned.
- `rename` uses Babel scope bindings and never touches property keys, labels or external names.
- `string_encode` never touches module specifiers, directive prologues or object/class keys.
- `operator_sub` rewrites are algebraically sound (fixed in v6.1: `a - b → +a + (-b)` handles
  non-numeric operands; `a*2 → +a + +a` avoids string concatenation traps).
- Dataset splits are disjoint by function id *and* code hash; provenance (`source_type`,
  repository, license) is tracked end-to-end.

## Security notes

Semantic validation executes untrusted JavaScript in Node `vm` with a timeout. **`node:vm` is not
a security boundary.** For any public-facing deployment, run validation in a separate sandboxed
process or container with resource limits. The demo is intended for trusted local input.

## Limitations

- MVP scope: standalone top-level named functions. Async, generators, JSX, TypeScript, DOM and
  code with external dependencies are rejected by the pipeline.
- Automatically synthesizing correct arguments for arbitrary functions is impossible in general;
  functions without 50 stable differential cases are discarded.
- Metric obfuscation (entropy/complexity/size) is not a cryptographic-strength claim.
- Within-intensity order diversity is mode-seeking under greedy decoding (10 unique orders vs 17
  in the data); the DPO stage is prepared to widen it.

## Roadmap

- [ ] DPO stage on 19,937 conditional preference pairs
- [ ] Class-method extraction for a larger real-code corpus
- [ ] Sandboxed validation container
- [ ] Public demo hosting

## License

[MIT](LICENSE). Third-party code collected into the dataset keeps its original license in the
provenance metadata; raw collected sources are not redistributed by this repository.
