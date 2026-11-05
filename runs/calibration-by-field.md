Correct = exact match (ignoring case and punctuation). Intervals: 95%, bootstrap over gaps (2000 resamples), none below 5 gaps.

1. Calibration per suggester and dataset

| suggester | dataset | field | runs | gaps | proposals | mean confidence | accuracy | 95% | over-confidence | Brier | ECE | 95% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | description | 6 | 8 | 47 | 0.54 | 40% | 12%-77% | +0.13 | 0.13 | 0.25 | 0.21-0.32 |
| agent-v3:gpt-oss-120b+evidence | dataset.json | partNumber | 6 | 4 | 18 | 0.64 | 89% | - | -0.24 | 0.09 | 0.29 | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | description | 4 | 9 | 36 | 0.57 | 22% | 0%-56% | +0.35 | 0.26 | 0.35 | 0.15-0.56 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | partNumber | 4 | 7 | 12 | 0.67 | 33% | 0%-71% | +0.33 | 0.32 | 0.33 | 0.03-0.67 |
| llm:gpt-oss-120b | dataset.json | description | 4 | 8 | 32 | 0.85 | 41% | 12%-75% | +0.45 | 0.39 | 0.45 | 0.17-0.71 |
| llm:gpt-oss-120b | dataset.json | partNumber | 4 | 4 | 10 | 0.82 | 100% | - | -0.18 | 0.05 | 0.18 | - |
| llm:gpt-oss-120b | dataset_cad.json | description | 4 | 9 | 36 | 0.77 | 8% | 0%-25% | +0.69 | 0.55 | 0.69 | 0.52-0.79 |
| llm:gpt-oss-120b | dataset_cad.json | partNumber | 4 | 2 | 7 | 0.64 | 0% | - | +0.64 | 0.42 | 0.64 | - |
| llm:gpt-oss-120b+evidence | dataset.json | description | 3 | 8 | 24 | 0.41 | 46% | 12%-79% | -0.05 | 0.17 | 0.08 | 0.03-0.30 |
| llm:gpt-oss-120b+evidence | dataset.json | partNumber | 3 | 2 | 6 | 0.70 | 100% | - | -0.30 | 0.09 | 0.30 | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json | description | 4 | 9 | 36 | 0.32 | 11% | 0%-33% | +0.21 | 0.16 | 0.21 | 0.06-0.34 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | partNumber | 4 | 4 | 7 | 0.70 | 14% | - | +0.56 | 0.43 | 0.56 | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | material | 3 | 5 | 15 | 0.47 | 67% | 33%-93% | -0.20 | 0.26 | 0.31 | 0.09-0.55 |
| rules | dataset.json | description | 2 | 8 | 16 | 0.46 | 50% | 12%-88% | -0.04 | 0.14 | 0.16 | 0.05-0.34 |
| rules | dataset.json | partNumber | 2 | 2 | 4 | 0.70 | 100% | - | -0.30 | 0.09 | 0.30 | - |
| rules | dataset_cad.json | description | 2 | 9 | 18 | 0.30 | 0% | 0%-33% | +0.30 | 0.09 | 0.30 | 0.30-0.30 |
| rules | dataset_cad.json | partNumber | 2 | 1 | 2 | 0.40 | 0% | - | +0.40 | 0.16 | 0.40 | - |
| rules | dataset_cad.json (material) | material | 1 | 6 | 6 | 0.50 | 67% | 33%-100% | -0.17 | 0.33 | 0.17 | 0.00-0.57 |

2. Accuracy per basis (evidence mode) and per rule (rules)

| suggester | dataset | field | basis | gaps | proposals | confidence given | accuracy | 95% |
|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | description | copied | 4 | 19 | 0.80 | 95% | - |
| agent-v3:gpt-oss-120b+evidence | dataset.json | description | pattern | 3 | 4 | 0.70 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset.json | description | inferred | 5 | 24 | 0.30 | 4% | 0%-12% |
| agent-v3:gpt-oss-120b+evidence | dataset.json | partNumber | pattern | 3 | 16 | 0.70 | 100% | - |
| agent-v3:gpt-oss-120b+evidence | dataset.json | partNumber | inferred | 1 | 1 | 0.30 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset.json | partNumber | guess | 1 | 1 | 0.10 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | description | copied | 6 | 13 | 0.80 | 46% | 0%-86% |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | description | pattern | 4 | 8 | 0.70 | 25% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | description | inferred | 5 | 15 | 0.30 | 0% | 0%-60% |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | partNumber | pattern | 7 | 11 | 0.70 | 36% | 0%-75% |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | partNumber | inferred | 1 | 1 | 0.30 | 0% | - |
| llm:gpt-oss-120b+evidence | dataset.json | description | copied | 2 | 3 | 0.80 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset.json | description | pattern | 2 | 3 | 0.70 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset.json | description | inferred | 6 | 18 | 0.30 | 28% | 0%-61% |
| llm:gpt-oss-120b+evidence | dataset.json | partNumber | pattern | 2 | 6 | 0.70 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json | description | pattern | 2 | 2 | 0.70 | 0% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json | description | inferred | 9 | 34 | 0.30 | 12% | 0%-35% |
| llm:gpt-oss-120b+evidence | dataset_cad.json | partNumber | pattern | 4 | 7 | 0.70 | 14% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | material | copied | 1 | 1 | 0.80 | 0% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | material | pattern | 4 | 5 | 0.70 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | material | inferred | 4 | 9 | 0.30 | 56% | - |
| rules | dataset.json | description | description-analogy | 3 | 6 | 0.73 | 100% | - |
| rules | dataset.json | description | title-expansion | 5 | 10 | 0.30 | 20% | 0%-60% |
| rules | dataset.json | partNumber | sibling-numbers | 2 | 4 | 0.70 | 100% | - |
| rules | dataset_cad.json | description | title-expansion | 9 | 18 | 0.30 | 0% | 0%-33% |
| rules | dataset_cad.json | partNumber | sibling-numbers | 1 | 2 | 0.40 | 0% | - |
| rules | dataset_cad.json (material) | material | sibling-material | 6 | 6 | 0.50 | 67% | 33%-100% |

3. Transfer: basis -> confidence fixed (0.8/0.7/0.3/0.1) or learned on one dataset, tested on the other

Thresholds are chosen on the training dataset: strict = no wrong write, tolerant = at most 10% wrong.

| suggester | field | learned on | tested on | mapping | ECE on test | strict threshold | test: written / wrong | tolerant threshold | test: written / wrong | test: wrong share |
|---|---|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | description | dataset.json | dataset_cad.json | fixed | 0.35 | none | 0.0 / 0.0 | 0.80 | 3.2 / 1.8 | 54% |
| agent-v3:gpt-oss-120b+evidence | description | dataset.json | dataset_cad.json | learned | 0.17 | none | 0.0 / 0.0 | 0.90 | 3.2 / 1.8 | 54% |
| agent-v3:gpt-oss-120b+evidence | description | dataset_cad.json | dataset.json | fixed | 0.25 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |
| agent-v3:gpt-oss-120b+evidence | description | dataset_cad.json | dataset.json | learned | 0.23 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |
| agent-v3:gpt-oss-120b+evidence | partNumber | dataset.json | dataset_cad.json | fixed | 0.33 | 0.70 | 2.8 / 1.8 | 0.30 | 3.0 / 2.0 | 67% |
| agent-v3:gpt-oss-120b+evidence | partNumber | dataset.json | dataset_cad.json | learned | 0.56 | 0.94 | 2.8 / 1.8 | 0.94 | 2.8 / 1.8 | 64% |
| agent-v3:gpt-oss-120b+evidence | partNumber | dataset_cad.json | dataset.json | fixed | 0.29 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |
| agent-v3:gpt-oss-120b+evidence | partNumber | dataset_cad.json | dataset.json | learned | 0.51 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | description | dataset.json | dataset_cad.json | fixed | 0.21 | 0.70 | 0.5 / 0.5 | 0.70 | 0.5 / 0.5 | 100% |
| llm:gpt-oss-120b+evidence | description | dataset.json | dataset_cad.json | learned | 0.22 | 0.80 | 0.5 / 0.5 | 0.80 | 0.5 / 0.5 | 100% |
| llm:gpt-oss-120b+evidence | description | dataset_cad.json | dataset.json | fixed | 0.08 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | description | dataset_cad.json | dataset.json | learned | 0.31 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | partNumber | dataset.json | dataset_cad.json | fixed | 0.56 | 0.70 | 1.8 / 1.5 | 0.70 | 1.8 / 1.5 | 86% |
| llm:gpt-oss-120b+evidence | partNumber | dataset.json | dataset_cad.json | learned | 0.73 | 0.88 | 1.8 / 1.5 | 0.88 | 1.8 / 1.5 | 86% |
| llm:gpt-oss-120b+evidence | partNumber | dataset_cad.json | dataset.json | fixed | 0.30 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | partNumber | dataset_cad.json | dataset.json | learned | 0.78 | none | 0.0 / 0.0 | none | 0.0 / 0.0 | - |

Saved runs\reliability-by-field.png
Saved runs\calibration-by-field.json
