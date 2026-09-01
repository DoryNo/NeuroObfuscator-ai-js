# NeuroObfuscator v7.1 — Evaluation Report

- Model: Qwen2.5-Coder-7B q8_0 GGUF (qwen2.5-coder-7b-instruct.q8_0.gguf)
- Test set: 750 records (conditional)
- JSON parse rate: **100.0%** (target >= 95%)
- Schema valid rate: **100.0%** (target >= 90%)
- Field obedience: **100.0%** | Shape obedience: **100.0%** (target >= 90%)
- Light purity: **100.0%** (target >= 95%)
- Semantic pass rate: **100.0%**
- Unique orders: 10 | top non-light: `rename > string_encode > operator_sub > dead_code` 19.0% (target <= 45%)

## Semantic pass by intensity

| intensity | passed | total | rate |
|---|---|---|---|
| light | 112 | 112 | 100.0% |
| medium | 355 | 355 | 100.0% |
| heavy | 283 | 283 | 100.0% |
