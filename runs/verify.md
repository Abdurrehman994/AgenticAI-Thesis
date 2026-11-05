Correct = exact match (ignoring case and punctuation). Unverified copies demoted to 0.30.

1. "Copied" answers by what the code could verify (95% bootstrap over gaps)

| suggester | dataset | check | gaps | answers | right | 95% |
|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | variant swap | 3 | 18 | 100% | - |
| agent-v3:gpt-oss-120b+evidence | dataset.json | unverified | 1 | 1 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | literal copy | 1 | 1 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | variant swap | 2 | 6 | 100% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | unverified | 3 | 6 | 0% | - |
| llm:gpt-oss-120b+evidence | dataset.json | variant swap | 2 | 3 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | literal copy | 1 | 1 | 0% | - |

2. Calibration with and without the check

| suggester | dataset | mapping | ECE | 95% |
|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | fixed | 0.18 | 0.12-0.27 |
| agent-v3:gpt-oss-120b+evidence | dataset.json | checked | 0.19 | 0.15-0.27 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | fixed | 0.34 | 0.16-0.54 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | checked | 0.30 | 0.17-0.45 |
| llm:gpt-oss-120b+evidence | dataset.json | fixed | 0.12 | 0.07-0.31 |
| llm:gpt-oss-120b+evidence | dataset.json | checked | 0.12 | 0.07-0.31 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | fixed | 0.27 | 0.10-0.43 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | checked | 0.27 | 0.10-0.43 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | fixed | 0.31 | 0.09-0.55 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | checked | 0.31 | 0.09-0.55 |

3. Transfer: tolerant threshold (at most 10% wrong) chosen on one dataset, applied to the other

| suggester | mapping | chosen on | tested on | threshold | test: written / wrong per run | test: wrong share |
|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | fixed | dataset.json | dataset_cad.json | 0.80 | 3.2 / 1.8 | 54% |
| agent-v3:gpt-oss-120b+evidence | checked | dataset.json | dataset_cad.json | 0.80 | 1.8 / 0.2 | 14% |
| agent-v3:gpt-oss-120b+evidence | fixed | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| agent-v3:gpt-oss-120b+evidence | checked | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | fixed | dataset.json | dataset_cad.json | 0.70 | 2.2 / 2.0 | 89% |
| llm:gpt-oss-120b+evidence | checked | dataset.json | dataset_cad.json | 0.70 | 2.2 / 2.0 | 89% |
| llm:gpt-oss-120b+evidence | fixed | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | checked | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |

Saved runs\verify.json
