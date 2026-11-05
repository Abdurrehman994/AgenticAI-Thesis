Correct = close match. One decision per gap: the majority answer over the repeated runs.

1. Agreement and correctness

| suggester | dataset | runs | graded gaps | decided | majority right | unanimous: gaps | right | 95% | split: gaps | right | 95% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | 6 | 12 | 12 | 92% | 6 | 100% | 50%-100% | 6 | 83% | 50%-100% |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | 4 | 17 | 16 | 38% | 3 | 100% | - | 13 | 23% | 0%-46% |
| llm:gpt-oss-120b | dataset.json | 4 | 12 | 12 | 83% | 6 | 100% | 50%-100% | 6 | 67% | 33%-100% |
| llm:gpt-oss-120b | dataset_cad.json | 4 | 17 | 11 | 18% | 2 | 50% | - | 9 | 11% | 0%-33% |
| llm:gpt-oss-120b+evidence | dataset.json | 3 | 12 | 10 | 80% | 5 | 100% | 40%-100% | 5 | 60% | 20%-100% |
| llm:gpt-oss-120b+evidence | dataset_cad.json | 4 | 17 | 13 | 23% | 1 | 100% | - | 12 | 17% | 0%-42% |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | 3 | 6 | 5 | 80% | 2 | 100% | - | 3 | 67% | - |

2. Calibration of each score over the gap decisions (95% bootstrap over gaps)

| suggester | dataset | score | mean score | right | ECE | 95% | Brier |
|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | basis | 0.58 | 92% | 0.33 | 0.20-0.48 | 0.18 |
| agent-v3:gpt-oss-120b+evidence | dataset.json | agreement | 0.71 | 92% | 0.21 | 0.08-0.39 | 0.14 |
| agent-v3:gpt-oss-120b+evidence | dataset.json | combined | 0.44 | 92% | 0.47 | 0.30-0.64 | 0.32 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | basis | 0.62 | 38% | 0.28 | 0.13-0.52 | 0.29 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | agreement | 0.50 | 38% | 0.16 | 0.06-0.31 | 0.14 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | combined | 0.32 | 38% | 0.16 | 0.08-0.35 | 0.14 |
| llm:gpt-oss-120b | dataset.json | basis | 0.84 | 83% | 0.06 | 0.03-0.30 | 0.15 |
| llm:gpt-oss-120b | dataset.json | agreement | 0.67 | 83% | 0.17 | 0.02-0.38 | 0.16 |
| llm:gpt-oss-120b | dataset.json | combined | 0.58 | 83% | 0.26 | 0.12-0.47 | 0.20 |
| llm:gpt-oss-120b | dataset_cad.json | basis | 0.76 | 18% | 0.58 | 0.39-0.77 | 0.48 |
| llm:gpt-oss-120b | dataset_cad.json | agreement | 0.57 | 18% | 0.39 | 0.23-0.59 | 0.27 |
| llm:gpt-oss-120b | dataset_cad.json | combined | 0.44 | 18% | 0.26 | 0.14-0.44 | 0.17 |
| llm:gpt-oss-120b+evidence | dataset.json | basis | 0.47 | 80% | 0.33 | 0.13-0.56 | 0.24 |
| llm:gpt-oss-120b+evidence | dataset.json | agreement | 0.70 | 80% | 0.10 | 0.00-0.33 | 0.12 |
| llm:gpt-oss-120b+evidence | dataset.json | combined | 0.38 | 80% | 0.42 | 0.22-0.65 | 0.31 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | basis | 0.43 | 23% | 0.29 | 0.11-0.47 | 0.23 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | agreement | 0.52 | 23% | 0.29 | 0.15-0.52 | 0.25 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | combined | 0.20 | 23% | 0.03 | 0.02-0.27 | 0.16 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | basis | 0.47 | 80% | 0.45 | 0.34-0.55 | 0.21 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | agreement | 0.80 | 80% | 0.00 | 0.00-0.33 | 0.13 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | combined | 0.37 | 80% | 0.51 | 0.35-0.62 | 0.28 |

3. Transfer: threshold chosen on one dataset (strict: no wrong write; tolerant: at most 10% wrong), applied to the other

| suggester | score | chosen on | tested on | strict threshold | test: written / wrong | tolerant threshold | test: written / wrong | test: wrong share |
|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | basis | dataset.json | dataset_cad.json | 0.60 | 11 / 6 | 0.30 | 16 / 10 | 62% |
| agent-v3:gpt-oss-120b+evidence | agreement | dataset.json | dataset_cad.json | 0.33 | 9 / 4 | 0.17 | 16 / 10 | 62% |
| agent-v3:gpt-oss-120b+evidence | combined | dataset.json | dataset_cad.json | 0.10 | 15 / 9 | 0.05 | 16 / 10 | 62% |
| agent-v3:gpt-oss-120b+evidence | basis | dataset_cad.json | dataset.json | 0.78 | 3 / 0 | 0.78 | 3 / 0 | 0% |
| agent-v3:gpt-oss-120b+evidence | agreement | dataset_cad.json | dataset.json | 0.75 | 6 / 0 | 0.75 | 6 / 0 | 0% |
| agent-v3:gpt-oss-120b+evidence | combined | dataset_cad.json | dataset.json | 0.52 | 5 / 0 | 0.52 | 5 / 0 | 0% |
| llm:gpt-oss-120b | basis | dataset.json | dataset_cad.json | 0.93 | 0 / 0 | 0.93 | 0 / 0 | - |
| llm:gpt-oss-120b | agreement | dataset.json | dataset_cad.json | 0.75 | 5 / 3 | 0.75 | 5 / 3 | 60% |
| llm:gpt-oss-120b | combined | dataset.json | dataset_cad.json | 0.55 | 5 / 3 | 0.55 | 5 / 3 | 60% |
| llm:gpt-oss-120b | basis | dataset_cad.json | dataset.json | none | 0 / 0 | none | 0 / 0 | - |
| llm:gpt-oss-120b | agreement | dataset_cad.json | dataset.json | none | 0 / 0 | none | 0 / 0 | - |
| llm:gpt-oss-120b | combined | dataset_cad.json | dataset.json | 0.78 | 5 / 0 | 0.78 | 5 / 0 | 0% |
| llm:gpt-oss-120b+evidence | basis | dataset.json | dataset_cad.json | 0.70 | 4 / 3 | 0.70 | 4 / 3 | 75% |
| llm:gpt-oss-120b+evidence | agreement | dataset.json | dataset_cad.json | 0.67 | 5 / 3 | 0.67 | 5 / 3 | 60% |
| llm:gpt-oss-120b+evidence | combined | dataset.json | dataset_cad.json | 0.20 | 6 / 4 | 0.20 | 6 / 4 | 67% |
| llm:gpt-oss-120b+evidence | basis | dataset_cad.json | dataset.json | none | 0 / 0 | none | 0 / 0 | - |
| llm:gpt-oss-120b+evidence | agreement | dataset_cad.json | dataset.json | 1.00 | 5 / 0 | 1.00 | 5 / 0 | 0% |
| llm:gpt-oss-120b+evidence | combined | dataset_cad.json | dataset.json | none | 0 / 0 | none | 0 / 0 | - |

Agreement costs one model call per run: 3+ calls per gap instead of one.
Saved runs\agreement-close.json
