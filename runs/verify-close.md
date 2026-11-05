Correct = close match. Unverified copies demoted to 0.30.

1. "Copied" answers by what the code could verify (95% bootstrap over gaps)

| suggester | dataset | check | gaps | answers | right | 95% |
|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | variant swap | 3 | 18 | 100% | - |
| agent-v3:gpt-oss-120b+evidence | dataset.json | unverified | 1 | 1 | 100% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | literal copy | 1 | 1 | 0% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | variant swap | 2 | 6 | 100% | - |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | unverified | 3 | 6 | 50% | - |
| llm:gpt-oss-120b+evidence | dataset.json | variant swap | 2 | 3 | 100% | - |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | literal copy | 1 | 1 | 0% | - |

2. Calibration with and without the check

| suggester | dataset | mapping | ECE | 95% |
|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | dataset.json | fixed | 0.34 | 0.24-0.47 |
| agent-v3:gpt-oss-120b+evidence | dataset.json | checked | 0.35 | 0.24-0.48 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | fixed | 0.20 | 0.07-0.40 |
| agent-v3:gpt-oss-120b+evidence | dataset_cad.json | checked | 0.15 | 0.06-0.37 |
| llm:gpt-oss-120b+evidence | dataset.json | fixed | 0.36 | 0.18-0.54 |
| llm:gpt-oss-120b+evidence | dataset.json | checked | 0.36 | 0.18-0.54 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | fixed | 0.15 | 0.04-0.36 |
| llm:gpt-oss-120b+evidence | dataset_cad.json | checked | 0.15 | 0.04-0.36 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | fixed | 0.31 | 0.09-0.55 |
| llm:gpt-oss-120b+evidence | dataset_cad.json (material) | checked | 0.31 | 0.09-0.55 |

3. Transfer: tolerant threshold (at most 10% wrong) chosen on one dataset, applied to the other

| suggester | mapping | chosen on | tested on | threshold | test: written / wrong per run | test: wrong share |
|---|---|---|---|---|---|---|
| agent-v3:gpt-oss-120b+evidence | fixed | dataset.json | dataset_cad.json | 0.10 | 12.0 / 7.2 | 60% |
| agent-v3:gpt-oss-120b+evidence | checked | dataset.json | dataset_cad.json | 0.10 | 12.0 / 7.2 | 60% |
| agent-v3:gpt-oss-120b+evidence | fixed | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| agent-v3:gpt-oss-120b+evidence | checked | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | fixed | dataset.json | dataset_cad.json | 0.70 | 2.2 / 1.8 | 78% |
| llm:gpt-oss-120b+evidence | checked | dataset.json | dataset_cad.json | 0.70 | 2.2 / 1.8 | 78% |
| llm:gpt-oss-120b+evidence | fixed | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |
| llm:gpt-oss-120b+evidence | checked | dataset_cad.json | dataset.json | none | 0.0 / 0.0 | - |

Saved runs\verify-close.json
