# NeuroObfuscator v6 — Evaluation Report

- Model: Qwen2.5-Coder-7B q4_k_m GGUF (qwen2.5-coder-7b-instruct.Q8_0.gguf)
- Test set: 750 records
- JSON parse rate: **100.0%** (target >= 95%)
- Schema valid rate: **100.0%** (target >= 90%)
- Semantic pass rate: **94.1%
- Intensity dist: {'heavy': 350, 'light': 64, 'medium': 336}
- Unique orders: 8 | top-order share: 62.3%

## Semantic pass by intensity

| intensity | passed | total | rate |
|---|---|---|---|
| light | 100 | 105 | 95.2% |
| medium | 276 | 296 | 93.2% |
| heavy | 330 | 349 | 94.6% |
