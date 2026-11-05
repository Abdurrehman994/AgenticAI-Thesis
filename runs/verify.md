Correct = exact match (ignoring case and punctuation). Claims the code cannot confirm are demoted to 0.30.

1. Checkable claims by what the code found (95% bootstrap over gaps)

| suggester | dataset | claim | check | verified | gaps | answers | right | 95% |
|---|---|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | copied | unverified | no | 1 | 1 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset.json | copied | variant swap | yes | 3 | 18 | 100% | - |
| agent-v3:gpt-oss-120b+evidence | dataset.json | pattern part number | only hole in the sequence | yes | 3 | 16 | 100% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | copied | literal copy | yes | 1 | 1 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | copied | unverified | no | 3 | 6 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | copied | variant swap | yes | 2 | 6 | 100% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | pattern part number | new variant of an existing family | no | 4 | 6 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | pattern part number | one of several holes | no | 3 | 5 | 80% | - |
| llm:gpt-oss-120b+evidence | dataset.json | copied | variant swap | yes | 2 | 3 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset.json | pattern part number | only hole in the sequence | yes | 2 | 6 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json | pattern part number | new variant of an existing family | no | 2 | 5 | 0% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json | pattern part number | one of several holes | no | 2 | 2 | 50% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | copied | literal copy | yes | 1 | 1 | 0% | - |

2. Calibration with and without the checks

| suggester | dataset | mapping | ECE | 95% |
|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | fixed | 0.18 | 0.12-0.27 |
| agent-v3:gpt-oss-120b+evidence | dataset.json | copies checked | 0.19 | 0.15-0.27 |
| agent-v3:gpt-oss-120b+evidence | dataset.json | numbers checked | 0.18 | 0.12-0.27 |
| agent-v3:gpt-oss-120b+evidence | dataset.json | both checked | 0.19 | 0.15-0.27 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | fixed | 0.34 | 0.16-0.54 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | copies checked | 0.30 | 0.17-0.45 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | numbers checked | 0.25 | 0.09-0.46 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | both checked | 0.21 | 0.07-0.37 |
| llm:gpt-oss-120b+evidence | dataset.json | fixed | 0.12 | 0.07-0.31 |
| llm:gpt-oss-120b+evidence | dataset.json | copies checked | 0.12 | 0.07-0.31 |
| llm:gpt-oss-120b+evidence | dataset.json | numbers checked | 0.12 | 0.07-0.31 |
| llm:gpt-oss-120b+evidence | dataset.json | both checked | 0.12 | 0.07-0.31 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | fixed | 0.27 | 0.10-0.43 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | copies checked | 0.27 | 0.10-0.43 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | numbers checked | 0.20 | 0.04-0.33 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | both checked | 0.20 | 0.04-0.33 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | fixed | 0.31 | 0.09-0.55 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | copies checked | 0.31 | 0.09-0.55 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | numbers checked | 0.31 | 0.09-0.55 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | both checked | 0.31 | 0.09-0.55 |

3. Transfer: tolerant threshold (at most 10% wrong) chosen on one dataset, applied to the other

| suggester | mapping | chosen on | tested on | threshold | test: written / wrong per run | test: wrong share |
|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | fixed | dataset.json | dataset_cad.json | 0.80 | 3.2 / 1.8 | 54% |
| agent-v3:gpt-oss-120b+evidence | copies checked | dataset.json | dataset_cad.json | 0.80 | 1.8 / 0.2 | 14% |
| agent-v3:gpt-oss-120b+evidence | numbers checked | dataset.json | dataset_cad.json | 0.80 | 3.2 / 1.8 | 54% |
| agent-v3:gpt-oss-120b+evidence | both checked | dataset.json | dataset_cad.json | 0.80 | 1.8 / 0.2 | 14% |
| agent-v3:gpt-oss-120b+evidence | fixed | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| agent-v3:gpt-oss-120b+evidence | copies checked | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| agent-v3:gpt-oss-120b+evidence | numbers checked | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| agent-v3:gpt-oss-120b+evidence | both checked | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | fixed | dataset.json | dataset_cad.json | 0.70 | 2.2 / 2.0 | 89% |
| llm:gpt-oss-120b+evidence | copies checked | dataset.json | dataset_cad.json | 0.70 | 2.2 / 2.0 | 89% |
| llm:gpt-oss-120b+evidence | numbers checked | dataset.json | dataset_cad.json | 0.70 | 0.5 / 0.5 | 100% |
| llm:gpt-oss-120b+evidence | both checked | dataset.json | dataset_cad.json | 0.70 | 0.5 / 0.5 | 100% |
| llm:gpt-oss-120b+evidence | fixed | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | copies checked | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | numbers checked | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | both checked | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |

Saved runs\verify.json
