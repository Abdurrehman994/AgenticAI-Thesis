Correct = exact match (ignoring case and punctuation). One decision per gap: the majority answer over the repeated runs.

1. Agreement and correctness

| suggester | dataset | runs | graded gaps | decided | majority right | unanimous: gaps | right | 95% | split: gaps | right | 95% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | 6 | 12 | 12 | 50% | 6 | 83% | 50%-100% | 6 | 17% | 0%-50% |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | 4 | 17 | 16 | 25% | 3 | 67% | - | 13 | 15% | 0%-38% |
| llm:gpt-oss-120b | dataset.json | 4 | 12 | 12 | 58% | 6 | 83% | 50%-100% | 6 | 33% | 0%-67% |
| llm:gpt-oss-120b | dataset_cad.json | 4 | 17 | 11 | 9% | 2 | 0% | - | 9 | 11% | 0%-33% |
| llm:gpt-oss-120b+evidence | dataset.json | 3 | 12 | 10 | 60% | 5 | 100% | 40%-100% | 5 | 20% | 0%-60% |
| llm:gpt-oss-120b+evidence | dataset_cad.json | 4 | 17 | 13 | 15% | 1 | 100% | - | 12 | 8% | 0%-25% |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | 3 | 6 | 5 | 80% | 2 | 100% | - | 3 | 67% | - |

2. Calibration of each score over the gap decisions (95% bootstrap over gaps)

| suggester | dataset | score | mean score | right | ECE | 95% | Brier |
|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | basis | 0.58 | 50% | 0.22 | 0.15-0.37 | 0.13 |
| agent-v3:gpt-oss-120b+evidence | dataset.json | agreement | 0.71 | 50% | 0.21 | 0.07-0.43 | 0.16 |
| agent-v3:gpt-oss-120b+evidence | dataset.json | combined | 0.44 | 50% | 0.23 | 0.17-0.31 | 0.07 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | basis | 0.62 | 25% | 0.40 | 0.21-0.57 | 0.29 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | agreement | 0.50 | 25% | 0.28 | 0.16-0.45 | 0.20 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | combined | 0.32 | 25% | 0.16 | 0.09-0.32 | 0.13 |
| llm:gpt-oss-120b | dataset.json | basis | 0.84 | 58% | 0.26 | 0.06-0.53 | 0.30 |
| llm:gpt-oss-120b | dataset.json | agreement | 0.67 | 58% | 0.21 | 0.02-0.46 | 0.24 |
| llm:gpt-oss-120b | dataset.json | combined | 0.58 | 58% | 0.20 | 0.10-0.46 | 0.21 |
| llm:gpt-oss-120b | dataset_cad.json | basis | 0.76 | 9% | 0.67 | 0.50-0.78 | 0.53 |
| llm:gpt-oss-120b | dataset_cad.json | agreement | 0.57 | 9% | 0.48 | 0.30-0.68 | 0.36 |
| llm:gpt-oss-120b | dataset_cad.json | combined | 0.44 | 9% | 0.35 | 0.18-0.53 | 0.22 |
| llm:gpt-oss-120b+evidence | dataset.json | basis | 0.47 | 60% | 0.13 | 0.09-0.37 | 0.16 |
| llm:gpt-oss-120b+evidence | dataset.json | agreement | 0.70 | 60% | 0.17 | 0.07-0.27 | 0.06 |
| llm:gpt-oss-120b+evidence | dataset.json | combined | 0.38 | 60% | 0.22 | 0.10-0.42 | 0.15 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | basis | 0.43 | 15% | 0.28 | 0.10-0.46 | 0.22 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | agreement | 0.52 | 15% | 0.37 | 0.21-0.58 | 0.29 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | combined | 0.20 | 15% | 0.05 | 0.02-0.25 | 0.13 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | basis | 0.47 | 80% | 0.45 | 0.34-0.55 | 0.21 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | agreement | 0.80 | 80% | 0.00 | 0.00-0.33 | 0.13 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | combined | 0.37 | 80% | 0.51 | 0.35-0.62 | 0.28 |

3. Transfer: threshold chosen on one dataset (strict: no wrong write; tolerant: at most 10% wrong), applied to the other

| suggester | score | chosen on | tested on | strict threshold | test: written / wrong | tolerant threshold | test: written / wrong | test: wrong share |
|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | basis | dataset.json | dataset_cad.json | 0.80 | 0 / 0 | 0.80 | 0 / 0 | - |
| agent-v3:gpt-oss-120b+evidence | agreement | dataset.json | dataset_cad.json | none | 0 / 0 | none | 0 / 0 | - |
| agent-v3:gpt-oss-120b+evidence | combined | dataset.json | dataset_cad.json | 0.47 | 4 / 1 | 0.47 | 4 / 1 | 25% |
| agent-v3:gpt-oss-120b+evidence | basis | dataset_cad.json | dataset.json | 0.80 | 3 / 0 | 0.80 | 3 / 0 | 0% |
| agent-v3:gpt-oss-120b+evidence | agreement | dataset_cad.json | dataset.json | none | 0 / 0 | none | 0 / 0 | - |
| agent-v3:gpt-oss-120b+evidence | combined | dataset_cad.json | dataset.json | 0.80 | 3 / 0 | 0.80 | 3 / 0 | 0% |
| llm:gpt-oss-120b | basis | dataset.json | dataset_cad.json | 0.93 | 0 / 0 | 0.93 | 0 / 0 | - |
| llm:gpt-oss-120b | agreement | dataset.json | dataset_cad.json | none | 0 / 0 | none | 0 / 0 | - |
| llm:gpt-oss-120b | combined | dataset.json | dataset_cad.json | 0.90 | 0 / 0 | 0.90 | 0 / 0 | - |
| llm:gpt-oss-120b | basis | dataset_cad.json | dataset.json | none | 0 / 0 | none | 0 / 0 | - |
| llm:gpt-oss-120b | agreement | dataset_cad.json | dataset.json | none | 0 / 0 | none | 0 / 0 | - |
| llm:gpt-oss-120b | combined | dataset_cad.json | dataset.json | none | 0 / 0 | none | 0 / 0 | - |
| llm:gpt-oss-120b+evidence | basis | dataset.json | dataset_cad.json | 0.70 | 4 / 3 | 0.70 | 4 / 3 | 75% |
| llm:gpt-oss-120b+evidence | agreement | dataset.json | dataset_cad.json | 0.67 | 5 / 4 | 0.67 | 5 / 4 | 80% |
| llm:gpt-oss-120b+evidence | combined | dataset.json | dataset_cad.json | 0.20 | 6 / 5 | 0.20 | 6 / 5 | 83% |
| llm:gpt-oss-120b+evidence | basis | dataset_cad.json | dataset.json | none | 0 / 0 | none | 0 / 0 | - |
| llm:gpt-oss-120b+evidence | agreement | dataset_cad.json | dataset.json | 1.00 | 5 / 0 | 1.00 | 5 / 0 | 0% |
| llm:gpt-oss-120b+evidence | combined | dataset_cad.json | dataset.json | none | 0 / 0 | none | 0 / 0 | - |

Agreement costs one model call per run: 3+ calls per gap instead of one.
Saved runs\agreement.json
