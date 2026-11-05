Correct = close match. Intervals: 95%, bootstrap over gaps (2000 resamples), none below 5 gaps.

1. Calibration per suggester and dataset

| suggester | dataset | field | runs | gaps | proposals | mean confidence | accuracy | 95% | over-confidence | Brier | ECE | 95% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | all | 6 | 12 | 65 | 0.57 | 91% | 79%-100% | -0.34 | 0.20 | 0.34 | 0.24-0.47 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | all | 4 | 16 | 48 | 0.59 | 40% | 16%-65% | +0.20 | 0.23 | 0.20 | 0.07-0.40 |
| llm:gpt-oss-120b | dataset.json | all | 4 | 12 | 42 | 0.84 | 83% | 62%-100% | +0.01 | 0.13 | 0.06 | 0.02-0.23 |
| llm:gpt-oss-120b | dataset_cad.json | all | 4 | 11 | 43 | 0.75 | 23% | 7%-43% | +0.52 | 0.44 | 0.52 | 0.33-0.68 |
| llm:gpt-oss-120b+evidence | dataset.json | all | 3 | 10 | 30 | 0.47 | 83% | 63%-100% | -0.36 | 0.26 | 0.36 | 0.18-0.54 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | all | 4 | 13 | 43 | 0.38 | 23% | 5%-45% | +0.15 | 0.23 | 0.15 | 0.04-0.36 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | all | 3 | 5 | 15 | 0.47 | 67% | 33%-93% | -0.20 | 0.26 | 0.31 | 0.09-0.55 |
| rules | dataset.json | all | 2 | 10 | 20 | 0.51 | 80% | 50%-100% | -0.29 | 0.21 | 0.29 | 0.13-0.50 |
| rules | dataset_cad.json | all | 2 | 10 | 20 | 0.31 | 0% | 0%-30% | +0.31 | 0.10 | 0.31 | 0.30-0.33 |
| rules | dataset_cad.json (material) | all | 1 | 6 | 6 | 0.50 | 67% | 33%-100% | -0.17 | 0.33 | 0.17 | 0.00-0.57 |

2. Accuracy per basis (evidence mode) and per rule (rules)

| suggester | dataset | field | basis | gaps | proposals | confidence given | accuracy | 95% |
|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | all | copied | 4 | 19 | 0.80 | 100% | - |
| agent-v3:gpt-oss-120b+evidence | dataset.json | all | pattern | 6 | 20 | 0.70 | 100% | 50%-100% |
| agent-v3:gpt-oss-120b+evidence | dataset.json | all | inferred | 6 | 25 | 0.30 | 80% | 55%-97% |
| agent-v3:gpt-oss-120b+evidence | dataset.json | all | guess | 1 | 1 | 0.10 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | all | copied | 6 | 13 | 0.80 | 69% | 22%-94% |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | all | pattern | 11 | 19 | 0.70 | 42% | 13%-68% |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | all | inferred | 6 | 16 | 0.30 | 12% | 0%-40% |
| llm:gpt-oss-120b+evidence | dataset.json | all | copied | 2 | 3 | 0.80 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset.json | all | pattern | 4 | 9 | 0.70 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset.json | all | inferred | 6 | 18 | 0.30 | 72% | 39%-94% |
| llm:gpt-oss-120b+evidence | dataset_cad.json | all | pattern | 6 | 9 | 0.70 | 22% | 0%-67% |
| llm:gpt-oss-120b+evidence | dataset_cad.json | all | inferred | 9 | 34 | 0.30 | 24% | 6%-48% |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | all | copied | 1 | 1 | 0.80 | 0% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | all | pattern | 4 | 5 | 0.70 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | all | inferred | 4 | 9 | 0.30 | 56% | - |
| rules | dataset.json | all | description-analogy | 3 | 6 | 0.73 | 100% | - |
| rules | dataset.json | all | sibling-numbers | 2 | 4 | 0.70 | 100% | - |
| rules | dataset.json | all | title-expansion | 5 | 10 | 0.30 | 60% | 20%-100% |
| rules | dataset_cad.json | all | sibling-numbers | 1 | 2 | 0.40 | 0% | - |
| rules | dataset_cad.json | all | title-expansion | 9 | 18 | 0.30 | 0% | 0%-33% |
| rules | dataset_cad.json (material) | all | sibling-material | 6 | 6 | 0.50 | 67% | 33%-100% |

3. Transfer: basis -> confidence fixed (0.8/0.7/0.3/0.1) or learned on one dataset, tested on the other

Thresholds are chosen on the training dataset: strict = no wrong write, tolerant = at most 10% wrong.

| suggester | field | learned on | tested on | mapping | ECE on test | strict threshold | test: written / wrong | tolerant threshold | test: written / wrong | test: wrong share |
|---|---|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | all | dataset.json | dataset_cad.json | fixed | 0.20 | 0.70 | 8.0 / 3.8 | 0.10 | 12.0 / 7.2 | 60% |
| agent-v3:gpt-oss-120b+evidence | all | dataset.json | dataset_cad.json | learned | 0.50 | 0.95 | 8.0 / 3.8 | 0.33 | 12.0 / 7.2 | 60% |
| agent-v3:gpt-oss-120b+evidence | all | dataset_cad.json | dataset.json | fixed | 0.34 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |
| agent-v3:gpt-oss-120b+evidence | all | dataset_cad.json | dataset.json | learned | 0.51 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | all | dataset.json | dataset_cad.json | fixed | 0.15 | 0.70 | 2.2 / 1.8 | 0.70 | 2.2 / 1.8 | 78% |
| llm:gpt-oss-120b+evidence | all | dataset.json | dataset_cad.json | learned | 0.51 | 0.80 | 2.2 / 1.8 | 0.80 | 2.2 / 1.8 | 78% |
| llm:gpt-oss-120b+evidence | all | dataset_cad.json | dataset.json | fixed | 0.36 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | all | dataset_cad.json | dataset.json | learned | 0.58 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |

Saved runs\reliability-close.png
Saved runs\calibration-close.json
