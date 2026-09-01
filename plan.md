# NeuroObfuscator: план реализации MVP

## Цель

За три недели получить воспроизводимый прототип, который:

1. Разбирает обычный JavaScript через Babel.
2. Извлекает функции и AST-признаки.
3. Создает и исполняет планы из `rename`, `string_encode`, `operator_sub`, `dead_code`, `opaque_predicates`.
4. Сравнивает поведение исходной и измененной функции на одинаковых входах.
5. Оценивает валидные кандидаты и готовит `train/val/test.jsonl`.
6. Позже принимает план от дообученной модели и показывает результат в Gradio.

TypeScript, JSX, браузерный DOM, асинхронные функции, генераторы и код с внешними зависимостями не входят в MVP.

## Принципы корректности

- Модель генерирует только JSON-план. Babel-движок изменяет AST.
- Одинаковый `seed` дает одинаковый результат.
- План валидируется до изменения кода.
- Ошибка любой трансформации отменяет весь вызов; частичный результат не возвращается.
- `rename` использует Babel scope bindings и не меняет property keys, labels и внешние имена.
- `string_encode` не меняет module specifiers, directive prologues и object/class keys.
- Сравнение поведения выполняется в изолированном `node:vm` с timeout.
- Датасет хранит provenance и hash исходника, чтобы исключить дубликаты и утечку между split.

## Порядок реализации

### Фаза 1. Transform Engine ✅ ЗАВЕРШЕНА

Файлы:

- ✅ `engine/plan.js`: схема MVP, нормализация и проверка порядка (5 трансформаций).
- ✅ `engine/random.js`: детерминированный PRNG.
- ✅ `engine/transforms/rename.js`: переименование локальных bindings.
- ✅ `engine/transforms/string_encode.js`: 4 метода (`charcode_array`, `charcode_concat`, `hex_escape`, `unicode_escape`).
- ✅ `engine/transforms/operator_sub.js`: замены `+`/`-`/`*2`/`===`/`!==` с настраиваемым `rate`.
- ✅ `engine/transforms/dead_code.js`: безопасные недостижимые блоки.
- ✅ `engine/transforms/opaque_predicates.js`: детерминированные opaque predicates (seed-controlled).
- ✅ `engine/apply_plan.js`: parser -> transforms -> generator.
- ✅ `engine/extract_functions.js`: извлечение автономных именованных функций.
- ✅ `engine/extract_features.js`: 18 AST-признаков (включая `identifier_count`, `param_count`, `max_nesting`, `try_catch_count`).
- ✅ `engine/test_runner.js`: differential execution, 50 наборов аргументов.
- ✅ `engine/index.js`: JSON CLI для Python-скриптов и файловый CLI для пользователя.

Готовность:

- ✅ Критические контракты движка покрыты unit-тестами (`tests/engine.test.js`, 9 тестов).
- ✅ Результат повторяем по seed, включая `opaque_predicates`.
- ✅ Исходный и измененный код дают одинаковые результаты на поддерживаемых примерах.
- ⬜ Невалидный план завершается ненулевым exit code.

### Фаза 2. Dataset Generator ✅ ЗАВЕРШЕНА

Поток:

1. ✅ `scripts/00_generate_synthetic.py`: 33 шаблона (15 base + 10 wave2 + 8 wave3 high-complexity).
2. ✅ `scripts/01_collect.py`: локальные пути + shallow clone Git URL + `source_type` provenance.
3. ✅ `scripts/02_filter.py`: извлечение функций (FunctionDeclaration + VariableDeclarator + exports), фильтрация 3-80 строк, дедупликация; для real — ослаблен фильтр branch/loop.
4. ✅ `scripts/03_extract_features.py`: добавление 18 AST-признаков.
5. ✅ `scripts/04_generate_plans.py`: адаптивное количество планов (4 base, 6 для CC≥5), diversity sampling (4 forced + N random).
6. ✅ `scripts/05_apply_and_validate.py`: применение, differential validation, диагностика failing transform.
7. ✅ `scripts/06_score_and_select.py`: score v2, source-aware quotas (`--real-target` + `--synthetic-target`), order capping.
8. ✅ `scripts/07_format_for_training.py`: SFT format с `complexity_class` hint, корректный `source_type`.
9. ✅ `scripts/08_split_dataset.py`: точные target sizes + source-aware sub-split, multi-seed в отдельный файл.

Дополнительные файлы:

- ✅ `scripts/smoke_pipeline.py`: smoke-тест полного пайплайна.
- ✅ `scripts/evaluate.py`: скрипт оценки метрик.
- ✅ `scripts/common.py`: общие утилиты для скриптов.

Готовность:

- ✅ Полный smoke pipeline проходит (78 → 50 selected → 40/5/5 split).
- ✅ Production pipeline прогнан с нуля: train 7 840, val 980, test 980.
- ✅ Ни один `id` не встречается более чем в одном split (проверяется assert).
- ✅ `source_type` корректно прокидывается от manifest до final metadata.
- ✅ Невалидные функции отбрасываются с диагностикой причины.

### Фаза 3. ML Model

- ⬜ CodeLlama 7B INT4 или совместимая доступная instruct-модель.
- ⬜ Unsloth + QLoRA: `r=32`, `alpha=64`, 3 эпохи как стартовая конфигурация.
- ⬜ Вход: код + AST-признаки + complexity_class + seed.
- ⬜ Выход: только JSON.
- ⬜ JSON parse/schema rate измеряются отдельно.
- ⬜ До трех повторов; затем детерминированный fallback-план.

### Фаза 4. Evaluation

- ⬜ JSON parse rate и plan validation rate.
- ⬜ Semantic pass rate.
- ⬜ Размер, token entropy и cyclomatic complexity до/после.
- ⬜ Время трансформации и выполнения.
- ⬜ Score сначала без субъективной LLM-деобфускации; этот показатель добавляется после MVP.

Примечание: `scripts/evaluate.py` уже создан.

### Фаза 5. Demo UI

- ✅ `app/main.py`: Gradio-приложение (файл существует, поддерживает 5 трансформаций).
- ⬜ JS input, plan JSON, before/after, validation result, metrics.
- ⬜ Синтаксическая ошибка и ошибка плана показываются явно.

### Фаза 6. Resource Manager

После MVP. На первом этапе только явный выбор model/fallback через конфигурацию.

## График

| Дни | Результат |
|---|---|
| 1-4 | Phase 1, тесты движка |
| 5-9 | Phase 2, smoke dataset и затем до 2K пар |
| 10-12 | Обучение, inference, validator |
| 13-14 | Evaluation report |
| 15-17 | Gradio demo |
| 18-21 | Исправления, документация, демонстрация |

## Риски MVP

- Автоматически подобрать корректные аргументы для произвольной функции невозможно. MVP использует ограниченный набор JSON-аргументов и отбрасывает функции, которые не дают стабильный результат.
- Выполнение недоверенного JS требует изоляции сильнее `node:vm`. Для публичного сервиса нужен отдельный процесс/container с лимитами; локальный MVP использует subprocess + timeout.
- Лицензии исходного кода должны сохраняться в provenance. Публиковать сырой собранный код без проверки лицензий нельзя.
- Метрики сложности и энтропии не доказывают криптографическую стойкость. Проект позиционируется как адаптивная обфускация исходного кода.

---

## Улучшение датасета: решения

Зафиксировано 2026-08-18:

- Q1: добавить две трансформации сейчас. Выбраны `operator_sub` и `opaque_predicates`; итого пять трансформаций MVP.
- Q2: contrastive best/worst (DPO-ready). **Реализация изменена**: текущая production-версия `06_score_and_select.py` использует top-1 scoring + order capping (без worst-plan поля). Contrastive поле можно вернуть при переходе на DPO.
- Q3: финальная цель скорректирована под реалистичный максимум real: `9 800` final records = `550 real` + `9 250 synthetic`.
- Target split: `7 840 train` + `980 val` + `980 test`.
- Target source split: `440/55/55 real` и `7 400/925/925 synthetic`.
- Multi-seed variants хранятся отдельно и не входят в основной test count.

---

## Прогресс улучшения датасета (14 шагов)

| # | Шаг | Состояние | Реализация |
|---|---|---|---|
| 1 | Git sources (real code) | 🟡 Частично | `01_collect.py --git-url` работает; manifest: 677 real файлов. Explicit `source_type` добавлен, но provenance нужно проверить после полного rerun |
| 2 | Synthetic 8K+ | ✅ Готово | `--count 5000` default (реально в manifest 18 000 synthetic) |
| 3 | Новые шаблоны (high CC) | ✅ Готово | 8 wave3 генераторов: `gen_graph_bfs`, `gen_balanced_brackets`, `gen_roman_numeral`, `gen_deep_nested`, `gen_multi_array_zip`, `gen_event_emitter`, `gen_rate_limiter`, `gen_lru_cache`. Итого 33 генератора |
| 4 | Diversity sampling | ✅ Готово | 4 forced plans (light-only, no-op_sub, string-forced, minimal) + N random. В `04_generate_plans.py` |
| 5 | Адаптивный plans-per-function | ✅ Готово | 10 планов для CC≥5, 6 для остальных. В `04_generate_plans.py` |
| 6 | Order capping 25% | ✅ Готово | Quota-aware selection ограничивает order до 25% без потери target count |
| 7 | Score formula v2 (identifier scramble) | ✅ Готово | `0.35*entropy + 0.25*complexity + 0.20*size + 0.20*identifier_scramble` в `06_score_and_select.py` |
| 8 | Ослабить size penalty | ✅ Готово | Центр сдвинут 2.0→2.5, range 2→3, max ratio 4→6 |
| 9 | Расширить ARGUMENT_SETS | ✅ Готово | 50 наборов (было 11→35→50). Nested arrays, reducer objects, edge cases |
| 10 | Диагностика failures | ✅ Готово | `05_apply_and_validate.py` аннотирует `failing_transform` и печатает summary по reasons |
| 11 | Filter contrastive noise | ⬜ Не применимо | Contrastive поля (`rejected_output`) убраны из текущего production формата. Вернуть при DPO |
| 12 | Hard negatives | ⬜ Не реализовано | Планируется для DPO-этапа |
| 13 | complexity_class в prompt | ✅ Готово | `complexity_class=heavy (cyclomatic_complexity=12)` добавлен в instruction |
| 14 | Multi-seed test eval | ✅ Готово | Multi-seed variants теперь пишутся в отдельный `test_multi_seed.jsonl` и не увеличивают основной test |

### Новые изменения для target 10K/25% real

- ✅ `source_type` прокидывается из raw manifest в filtered records и final metadata.
- ✅ `07_format_for_training.py` больше не определяет synthetic/real по слову `github` в пути.
- ✅ `06_score_and_select.py` добавлены строгие source quotas: `2500 real + 7500 synthetic`.
- ✅ Order cap применяется совместно с source quotas; при невозможности выполнить обе квоты pipeline завершается ошибкой.
- ✅ `08_split_dataset.py` добавлены точные размеры `8000/1000/1000` и source quotas `2000/250/250`.
- ✅ `test_multi_seed.jsonl` отделён от основного test.
- ⬜ Production rerun ещё не выполнен: текущих `206` real filtered functions недостаточно для target `2500`.

---

## Текущее состояние датасета (production прогон v4, 2026-08-23)

### Что сделано в v4

- ✅ `UNSUPPORTED_RUNTIME` расширен (`require|process|Buffer|globalThis|window|document`): −115 функций, все — реальные краши песочницы движка.
- ✅ Планы `--plans-per-function 5` (`:0` baseline, `:1` без op_sub, `:2` string_encode, `:3` rename+dead со случайной интенсивностью, `:4` случайный); детерминизм `_rng_seed` сохранён — старый `validated.jsonl` переиспользован.
- ✅ Чанковая валидация c0..c7 (~7 000 записей, 0 крэшей движка); мердж `validated_full` = 70 075, дублей `candidate_id` = 0 (детерминизм подтверждён).
- ✅ `06_score_and_select.py`: `--intensity-targets` как стейджированные доли + двухфазный source-aware отбор (сначала весь real под общими счётчиками order-cap).
- ✅ `08_split_dataset.py`: точная послоевая аллокация — Hamilton по ячейкам (source × complexity × generator), reconcile до точных размеров, балансировка order-долей обменами внутри ячеек, хард-пост-условия (id/code-hash, ±5 п.п., real-счётчики).
- ✅ `12_build_dpo.py`: seed в rejected выровнен с seed промпта.
- ✅ `09_audit_dataset.py`: режим `--enforce` (order ≤22%, покрытие трансформаций, intensity ≤60%, стратификация ≤5 п.п., p95 ≥0.35); подключён последним шагом в `smoke_pipeline.py`.

### Артефакты v4

| Файл | Записей |
|---|---:|
| `data/filtered/functions.jsonl` | 13 992 (10 000 synthetic + 3 992 real) |
| `data/candidates/plans_v4.jsonl` | 69 960 (13 992 × 5) |
| `data/candidates/plans_extra.jsonl` | 55 968 (`:1..:4`) |
| `data/candidates/validated_full.jsonl` | 70 075 (passed: 52 010) |
| `data/candidates/scored_v4.jsonl` | 8 300 (real 1 000 + synthetic 7 300) |
| `data/final/formatted_v4.jsonl` | 8 300 |
| `data/final_v4/train.jsonl` | 6 640 (real 900) |
| `data/final_v4/val.jsonl` | 830 (real 50) |
| `data/final_v4/test.jsonl` | 830 (real 50) |
| `data/final/dpo_pairs_v4.jsonl` | 9 854 |
| `data/final/hard_negatives_v4.jsonl` | 303 |

### Метрики качества v4

| Показатель | Значение | Цель |
|---|---|---|
| Top order share | 20.0% (dataset), ≤20.5% (сплиты) | ≤20% / ≤22% enforce |
| Unique orders | 24 | ≥15 |
| string_encode (из записей со строками) | 85.1% | ≥60% |
| operator_sub (из записей с операторами) | 44.4% | ≥40% |
| opaque_predicates | 68.8% | ≥10% |
| Intensity L/M/H | 25.8 / 52.5 / 21.7% | 25–35 / 45–55 / 15–30% |
| Score p95 | 0.448 | ≥0.35 |
| Real в train | 900 | 900 |
| DPO пары (seed-aligned) | 9 854 | ≥1 000 |
| Hard negatives (informative) | 303 | см. отклонения |
| Split overlap (id/code-hash) | 0 | 0 |
| npm test | 12/12 | pass |
| smoke_pipeline (+--enforce) | passed | pass |

### Отклонения от исходного плана

- **total-target 8300 вместо 9000**: order-cap 0.20 математически ограничивает пул top-1-per-function на 8 644 записях; при цели 9000 real не добирался (глобальный greedy вытеснял слабоскорящиеся real из-под капа). Исправлено двухфазным отбором, объём снижен в пределах лестницы (≥7 200).
- **Квоты intensity как доли, а не счётчики**: точные цели неисполнимы в принципе — light в пуле 2 518 < 2 700, medium 4 468 < 4 500.
- **Hard negatives 303 < 500**: включены только информативные отказы (`output_mismatch`, `transformed_execution_error`). Доминирующий `insufficient_stable_cases` (~14.5 тыс.) — свойство функции, а не плана: у всех 3 606 таких функций нет ни одного прошедшего плана, их включение загрязнило бы артефакт.
- **Стратификация generator_type проверяется условно по источнику**: поле существует только у synthetic; фиксированные real 900/50/50 дают неизбежный сдвиг доли `None` между сплитами (6% в val против 12% глобально).

---

## Оставшиеся задачи (Next Steps)

### Пока модель обучается

1. **Gradio demo UI** — доделать `app/main.py`:
   - Input: JS код
   - Output: side-by-side before/after, JSON plan, metrics (entropy, complexity, size)
   - Auto mode (fallback plan) + model mode (JSON plan от модели)
   - Показывать ошибки парсинга и validation явно
   - Кнопка "Validate" — прогнать differential test

2. **Evaluation pipeline** — доработать `scripts/evaluate.py`:
   - JSON parse rate
   - Schema validation rate
   - Semantic pass rate (apply + validate)
   - Score distribution (histogram)
   - Per-intensity и per-source breakdown
   - Latency per plan
   - Автоматический отчёт в JSON + markdown

3. **Inference wrapper** — создать `scripts/inference.py`:
   - Загрузка модели (Unsloth merged или LoRA adapter)
   - Prompt formatting (instruction template из `07_format_for_training.py`)
   - JSON extraction + schema validation
   - Retry logic (до 3 попыток)
   - Fallback plan при неудаче
   - Batch inference для evaluation

4. **Расширить real corpus** (для v2 dataset):
   - Добавить class method extraction в `extract_functions.js`
   - Клонировать stdlib-js (крупный, rich pure JS)
   - Увеличить timeout для git clone крупных repos
   - Цель: 2500+ unique real functions после validation

5. **Score ceiling** — поднять max score:
   - Снизить penalty identifier_scramble для low-CC functions
   - Или добавить бонус за использование всех 5 трансформаций одновременно
   - Цель: score max >= 0.70

6. **DPO dataset** — подготовить best/worst pairs:
   - Вернуть worst-plan selection в scoring
   - Фильтровать gap < 0.05
   - Отдельный файл `data/final/dpo_pairs.jsonl`

### После обучения

7. **Evaluation report** — прогнать evaluate.py на test set с моделью
8. **Iterative improvement** — если JSON parse rate < 95%, добавить примеры с ошибками в train
9. **Демо-видео** — записать screencast Gradio с реальным примером

---

## Проверки 2026-08-20

- ✅ `npm test`: 9/9 passed.
- ✅ `python scripts/smoke_pipeline.py`: passed (78 → 468 → 50 → 40/5/5).
- ✅ Production dataset собран с нуля: 9 800 records, train 7 840, zero overlap.
- ✅ Source-aware quotas: 550 real + 9 250 synthetic.
- ✅ `source_type` корректен через весь pipeline.
- ✅ `extract_functions.js` расширен: поддерживает `const fn = function(){}`, arrow functions, exports.
- ✅ Filter ослаблен для real code (не требует branch/loop).
- ✅ Real repositories: 10+ open-source проектов (MIT/Apache licensed).
- ✅ Order capping 30%: top order 26.2%.


---

## Улучшение датасета v5 (2026-08-24)

### Изменения

1. **Аудит противоречий** (`scripts/10_audit_contradictions.py`): 6 правил (R1-R6) проверяют план против правил промпта. Флаги `--clean` / `--hard-only`.
2. **Починка R2b** (`scripts/14_fix_r2b.py`): 347 кандидатов с `operator_sub` при `operator_count <= 2` заменены на чистые альтернативы из validated_full. Потерь: 0.
3. **Смягчение R4**: SYSTEM_PROMPT разрешает opaque_predicates на light-функциях ("sparingly ... when extra diversity is needed").
4. **Обогащение редких порядков** (`scripts/15_enrich_rare_orders.py`): +238 extras из unused synthetic-пула; rare-порядки добиты, no-rename записи 8.3%.
5. **Маскирование seed**: seed удалён из training output (модель не учится предсказывать случайные числа). Промпт говорит "Do NOT include a seed field". inference.py инжектирует seed из промпта; валидатор принимает планы без seed.

### Артефакты v5

| Файл | Записей |
|---|---:|
| `data/final_v5_noseed/train.jsonl` | 6 840 (real 900) |
| `data/final_v5_noseed/val.jsonl` | 850 (real 50) |
| `data/final_v5_noseed/test.jsonl` | 850 (real 50) |

### Метрики v5 vs v4_fixed

| Показатель | v4_fixed | v5 |
|---|---|---|
| Уникальных порядков (train) | 24 | 27 |
| Записи без rename | ~6% | 8.4% |
| Жёсткие противоречия | 0 | 0 |
| Seed в output | есть (шум) | нет |
| Топ-order share | 23.5% | ~22.7% |

Примечание: `data/final_v5/` — промежуточная версия с seed в output; финальная для обучения — `data/final_v5_noseed/`.

## Фикс движка v6.1: нечестные подстановки operator_sub (2026-08-30)

`operator_sub` заменял `a - b` на `a + (-b)` — не эквивалентно в JS при нечисловом
левом операнде (`[100] - 5 = 95`, но `[100] + -5 = "100-5"`). На demo-примере
`calculateDiscount` из `colab_inference_l4_v6.ipynb` это давало `output_mismatch`
на args `[[100]]`; часть из 28 `output_mismatch` в eval v6 — тот же корень.

Исправления в `engine/transforms/operator_sub.js`:
- `a - b -> +a + (-b)`: `-` приводит операнды к числу, поэтому левый операнд
  явно коерсится через унарный `+`.
- `a + b -> a - (-b)`: только когда оба операнда — числовые литералы
  (иначе конкатенация в оригинале).
- `a * 2 -> a + a` заменён на `+a + +a` (`"5"*2=10`, но `"5"+"5"="55"`).
- `===`/`!==` без изменений (звуковые всегда).

Ограничение: унарный `+` бросает TypeError на BigInt — такие функции отсеются
differential-валидацией (`transformed_execution_error`), тихой порчи нет.

Проверки: `npm test` 13/13 (добавлен регрессионный тест на args-массивы);
demo-сценарий из ноутбука с тем же планом/seed — 50/50. Обновлён
`engine_bundle_v6.zip` (перезалить на Drive перед повторным eval).

---

## План v7: устранение mode collapse датасета (создан 2026-08-30)

### Контекст и диагноз

Eval v6 после фикса движка: parse 100%, schema 100%, semantic pass **100%** (750/750).
Корректность закрыта, осталась **diversity**: unique orders = 8, top-order share 62.3%,
intensity модели heavy 46.7% / light 8.5%.

Модель точно воспроизводит датасет — датасет сам схлопнут. Фактические числа
`final_v6/train.jsonl` (6000 записей):

| Показатель | v6 факт | v6 цель |
|---|---|---|
| Top order (`rename>operator_sub>dead_code>opaque_predicates`) | **60.5%** (4500/7500) | ≤22% |
| Unique orders | 24 | — |
| Intensity L/M/H | 15.2 / 37.2 / 47.6% | 28 / 48 / 24% |
| Покрытие string_encode (записи со строками) | ~30% | ≥60% |

Первопричины:

1. `scored_v6.jsonl` нарушает собственные квоты (top order 60% при cap 0.22).
   Текущий код `06_score_and_select.py` (жёсткий order cap в `accept()`) такой
   результат дать не может — прогон v6 выполнен неактуальной/изменённой версией
   скрипта ("v6 relevance bonus"). Воспроизводимость сборки нарушена.
2. `run_v6.sh` пропускает `09_audit_dataset.py --enforce` и `10_audit_contradictions.py`
   — коллапс прошёл незамеченным.
3. `08_split_dataset.py` получил 7500 записей при заказе 7200+900+900 (сумма 9000):
   reconcile молча уменьшил сплиты до 6000/750/750. Отклонение не подсвечено.
4. Топ-порядок v6 не содержит `string_encode` — score v6 (relevance bonus) недооценивал
   entropy-вклад string_encode, top-1 per function выбирал планы без него.
5. Top-1-per-function в `06` не оставляет пул для conditional-формата: одну функцию
   нельзя взять с разными intensity.

### Целевые метрики v7 (гейты приёмки)

| Показатель | Цель |
|---|---|
| Top order share (train и каждый сплит) | ≤15% |
| Unique orders (train) | ≥20 |
| Intensity L/M/H | 28 / 48 / 24% ± 5 п.п. |
| string_encode (из записей со строками) | ≥70% |
| opaque_predicates | ≥40% |
| dead_code | ≥60% |
| Real в train | 1200 (1500/150/150 по сплитам) |
| Overlap по id/code-hash между сплитами | 0 |
| `09_audit_dataset.py --enforce` | pass |
| Жёсткие противоречия (`10`) | 0 |
| Score p95 | ≥0.35 |
| `npm test` / `smoke_pipeline.py` | pass |

### Шаги

**Шаг 0. Диагностика и защита от регрессии (06)**

- Сухой прогон текущего `06_score_and_select.py` на `validated_v6.jsonl` с параметрами
  из `run_v6.sh`: подтвердить, что теперь top order ≤22% и intensity ≈ 28/48/24.
- В `06` заменить warnings на hard post-conditions: raise, если top order > cap,
  intensity-отклонение > 5 п.п. или coverage-пол не выполнен. Пайплайн падает сразу,
  а не отдаёт схлопнутый датасет.

**Шаг 1. Selection v7 (06)**

- Top-1 per function → **top-1 на ячейку (function × intensity)**: разрешить до 2–3
  планов на функцию с разными intensity (пул уже есть — `04 --intensity-seeded`
  генерирует `:c0..:c2` sweep-кандидаты, `validated_v6.jsonl` переиспользуется).
- Параметры: total 9000 (real 1500 + synthetic 7500), `--max-order-share 0.15`.
- Новые coverage-полы в selection: string_encode ≥70% (от записей со строками),
  opaque_predicates ≥40%, dead_code ≥60% — как счётчики наравне с order cap.
- После greedy — балансировочный pass локальными обменами, чтобы уложиться в caps
  без потери target counts (аналог `_balance_order_shares` из 08, но до сплита).

**Шаг 2. Conditional-формат (07)**

- В instruction добавить управляемые поля: `intensity` (и опционально
  `preferred_transforms`). Промпт: "Target intensity: heavy" — модель становится
  условным генератором, diversity управляется промптом, а не только статистикой.
- Датасет собирается из ячеек шага 1: одна функция может встречаться 2–3 раза
  с разными intensity-условиями (дедупликация по (id, intensity)).
- Seed остаётся вне output (noseed-режим сохраняется).

**Шаг 3. Сплит (08)**

- Заказ 7200/900/900 = 9000 ровно; добавить assert: если входной файл не равен сумме
  размеров — ошибка, а не тихий reconcile.
- Stratify по (source, complexity, intensity); `--max-order-share 0.15`.
- `test_multi_seed.jsonl` отдельно, как в v5.

**Шаг 4. Аудит и воспроизводимость (09/10 + run_v7.sh)**

- `09_audit_dataset.py --enforce` и `10_audit_contradictions.py` включить в
  `run_v7.sh` обязательными шагами после 08.
- В 09 добавить гейты: unique orders ≥20, per-transform coverage полы.
- `run_v7.sh` дублирует параметры v6 (04 → 05 переиспользует `validated_v6.jsonl`,
  06–08 новые), чтобы сборка была одно-командной и воспроизводимой.

**Шаг 5. DPO-пары (12)**

- Пересобрать `dpo_pairs_v7.jsonl` из `all_scored_v7.jsonl`: seed-aligned rejected,
  фильтр gap ≥0.05, цель ≥1500 пар.
- Балансировать пары по intensity-условиям, чтобы DPO не усилил collapse.

**Шаг 6. Приёмка**

- Прогнать smoke_pipeline (обновить под новыми флагами), затем production v7.
- Сверить все гейты из таблицы выше; обновить этот раздел фактическими числами.
- Движок не меняется (v6.1), `engine_bundle` пересборки не требует.

### После пересборки (вне этого плана)

- Дообучение SFT на `final_v7` (тот же Qwen2.5-Coder-7B), затем eval v7 c сравнением
  с v6 (diversity: unique orders, top-order share, intensity dist при semantic ≥98%).
- Затем DPO-стадия и Gradio demo с выбором intensity.

---

## Датасет v7: результат (2026-08-31)

Все шаги плана v7 выполнены. Движок не менялся (`validated_v6.jsonl` переиспользован).

### Что изменилось в пайплайне

- `06_score_and_select.py` — переписан: top-1 на ячейку (function × intensity) вместо
  top-1 per function (`--allow-multi-intensity`); score v7 (string_encode бонус
  0.05→0.10, op_sub 0.10→0.05, size sweet-spot 2.5→3.0/диапазон 4/max 8);
  coverage-полы как hard post-conditions; swap-балансировщики (order cap,
  coverage, intensity); staging intensity в порядке возрастания дефицита
  (scarce-first); `--drop-contradictions` (R2b + R4 отфильтровываются до selection).
  Полный пул кандидатов вместо top-1 пула: старый код не мог добрать 7500 при
  cap 0.22 (max 5570) — вот почему прогон v6 был сделан с обходом квот.
- `07_format_for_training.py` — `--conditional`: "Target intensity: X" в промпте,
  id = `{fid}@{intensity}`, `metadata.base_id`.
- `08_split_dataset.py` — group-mode: все intensity-варианты функции атомарно в одном
  сплите (нулевой base-overlap), relative-deficit greedy + reconcile до точных
  размеров, group-level order balancer (двухуровневый поиск партнёров).
- `09_audit_dataset.py` — новые гейты: unique orders ≥20 (train), coverage-полы
  string_encode/dead_code/opaque (из features промпта), top order ≤0.15.
- `12_build_dpo.py` — `--conditional` (пары по (function × intensity)) +
  `--drop-contradictions`.
- `inference.py` — `--intensity` (conditional промпт), fallback-план учитывает
  target intensity.
- `scripts/run_v7.sh` — одно-командная воспроизводимая сборка с аудит-гейтами.

### Артефакты v7

| Файл | Записей |
|---|---:|
| `data/candidates/scored_v7.jsonl` | 7 500 (real 900 + synthetic 6 600) |
| `data/final_v7/train.jsonl` | 6 000 (real 720) |
| `data/final_v7/val.jsonl` | 750 (real 90) |
| `data/final_v7/test.jsonl` | 750 (real 90) |
| `data/final_v7/dpo_pairs_v7.jsonl` | 19 937 (conditional, gap ≥ 0.05) |

### Метрики v7 vs v6

| Показатель | v6 | v7 | Гейт |
|---|---|---|---|
| Top order share (train) | 60.5% | **14.0%** | ≤15% |
| Unique orders (train) | 24 | **26** | ≥20 |
| Intensity L/M/H | 15.2/37.2/47.6% | **28.4/47.5/24.2%** | 28/48/24 ±5 п.п. |
| string_encode (со строками) | ~30% | **99.9%** | ≥70% |
| dead_code | — | 95.5% | ≥60% |
| opaque_predicates | — | 54.3% | ≥40% |
| Противоречия R1–R6 | 1234 (R2b 77 + R4 1157) | **0** | 0 |
| Base-function overlap между сплитами | — | **0** | 0 |
| Multi-intensity функций | 0 | 2 737 (в v7 selected: 5 464 функций → 7 500) | — |
| `09 --enforce` | не запускался | **passed** | pass |
| `npm test` / smoke | 13/13 | 13/13 / passed | pass |

### Инструкция по обучению v7

1. SFT на `data/final_v7/train.jsonl` (conditional-формат, тот же Unsloth/QLoRA конфиг).
2. DPO на `data/final_v7/dpo_pairs_v7.jsonl` (пар в 2 раза больше v6).
3. Eval: `scripts/evaluate.py` + ноутбук — промпт теперь с `Target intensity`;
   в eval проверять соблюдение intensity (light-планы не должны содержать opaque/op_sub).
4. Диверсити-метрики eval v7: unique orders (цель ≥15 у модели), top-order share
   (цель ≤25%), intensity dist при semantic pass ≥98%.

---

## Датасет v7.1: intensity как форма плана (2026-08-31)

Первое SFT v7 (Qwen2.5-Coder-3B, 3 эпохи) показало: parse 100%, schema 100%,
obedience поля 100%, но **light purity 4.3%** и unique orders 8 / top 30%.
Диагноз `tmp/diagnose_v7.py`: **модель точно воспроизвела данные** — в самом train
light purity была 2.3% (light-планы содержали 4 трансформа), интенсивность была
копией complexity_class и не влияла на контент; контраст вариантов одной функции
был не согласован с intensity (light мог быть жирнее heavy). Поле `intensity`
модель копирует из промпта, а контент учила из фич.

### Фикс: intensity определяет форму плана

`06_score_and_select.py --conditional-shapes` фильтрует пул по форме:

- **light** = `{rename}` или `{rename, dead_code}` (минимум)
- **medium** = 2–4 трансформа, **без** opaque_predicates, ≥1 из string_encode/operator_sub
- **heavy** = opaque_predicates обязательно, ≥3 трансформа, string_encode при строках

Квоты `light=20, medium=45, heavy=35` (light даёт один порядок — его доля
намеренно равна квоте). Order cap пересчитан от **non-light** популяции
(`expected_non_light × max_share`), light исключён из cap и из diversity-гейта.
`09`: гейты переехали на non-light share + новый `--enforce-min-light-purity 0.95`.
`07`/`inference.py`: SYSTEM_PROMPT описывает форму явно. `08`: балансировщик
предпочитает равноразмерные группы + повторный reconcile после балансировки.

### Метрики v7.1 (итог)

| Показатель | v7.0 | **v7.1** | Гейт |
|---|---|---|---|
| Light purity в train | 2.3% | **100%** (1236/1236) | ≥95% |
| Контраст вариантов одной функции | 70.8% (несогласованный) | **100% DIFF order** (1204/1204) | — |
| Top non-light order (train) | 60.5% (v6) / 14.0% | **11.4%** | ≤15% |
| Unique orders (train) | 8 у v6-модели | **22** | ≥20 |
| Intensity L/M/H | 15/37/48 | **20.6/41.5/37.9** | 20/45/35 ±5 п.п. |
| string_encode (со строками) | ~30% (v6) | **99.3%** | ≥70% |
| Противоречия | 1234 (v6) | **0** | 0 |
| Base overlap сплитов | 0 | **0** | 0 |
| `09 --enforce` / smoke / npm test | — | **passed / passed / 13** | pass |

Семантика условности теперь однозначна: light = всегда `rename>dead_code`,
medium = никогда без opaque, heavy = всегда с opaque; между вариантами одной
функции order всегда различается → у модели есть явный сигнал следовать
`Target intensity` контентом плана, а не только полем.

### Действия для переобучения

1. Перезалить `data/final_v7/{train,val}.jsonl` на Drive (датасет пересобран).
2. Перезапустить `colab_train_v7.ipynb` (ноутбук не менялся).
3. Ожидания eval: light purity ≥95%, obedience ≥90% (поле+контент), unique orders
   ≥15 у модели, top non-light ≤20%; semantic pass на движке ≥98%.
