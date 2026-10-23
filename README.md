# Agentic AI for PLM: attribute enrichment on 3DEXPERIENCE

Master's thesis project (University of Oulu). An agent finds missing attributes on Engineering Items in a
3DEXPERIENCE cloud tenant, proposes values from evidence in the product structure, and writes them back so a
human reviewer can approve or reject each one.

The integration uses only the public REST Web Services (`dseng` Engineering API) that come with a named-user
role. The Enterprise Integration Architect role and platform events are not available, so the agent **pulls**:
search → decide → write back.

```
AI agent (gap detection, suggesters)  →  Python REST client  →  3DEXPERIENCE public REST (dseng)
```

## Status

| Phase | Scope | State |
|---|---|---|
| 1. Validate access | Postman calls against the Engineering API | Done |
| 2. REST client | 3DPassport login, CSRF, search, GET/PATCH, recorded offline replay | Done |
| 3. Agent logic | Gap detection, rule-based suggester, `[PROPOSED]` write-back, review | Done |
| 4. Evaluation | Score proposals against ground truth; held-out CAD dataset; rules vs. LLM comparison | In progress: LLM runs wait for Lehmus AI access |

## How the agent works

1. **Snapshot**: search every Engineering Item in one collab space; fetch BOM children and where-used parents on demand.
2. **Gap detection** (plain code, no AI): list empty `description` and `partNumber` fields.
3. **Suggesters** propose a value with a confidence score and the evidence used:
   - *description by analogy*: copy the description of a same-family item whose title differs only in a variant token
     (`API_NUT_M8_ISO4032` "Hex nut M8 …" → `API_NUT_M6_ISO4032` "Hex nut M6 …")
   - *sibling part numbers*: fill the one number missing among the other parts in the same assembly
     (GRD-3001, GRD-3003, GRD-3004 → GRD-3002)
   - *title expansion*: low-confidence fallback built from the item title
   - *LLM* (`agent/llm.py`): any OpenAI-compatible endpoint (Lehmus AI, Ollama, commercial APIs). One request
     per gap with the same evidence the rules see (parents, siblings, children, other items in the collab space);
     the model answers with a value or null, a confidence and the evidence it used. Part numbers already in use
     are refused, and a part number proposed for two items in the same run is dropped for both.
4. **Write-back for review**: descriptions are written as `[PROPOSED] value`, so reviewers see them in the
   3DEXPERIENCE app. Part numbers are identifiers, so they are only logged and written on approval. Every proposal
   and decision is appended to `runs/proposals.jsonl`.
5. **Review**: approve (optionally with an edited value) or reject (restores the old value). A field changed in PLM
   after the proposal was written is refused as a conflict.

## Setup

Requires Python 3.11+ and an account with access to the Engineering Web Services.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env    # then fill in tenant URLs, credentials and SecurityContext
```

`PLM_SECURITY_CONTEXT` is `Role.Organization.CollabSpace`, the same value as the `SecurityContext` header in Postman.

## Usage

Scripts that change the tenant are dry runs unless given `--yes` or `--apply`.

```powershell
# Phase 2 checkpoint: log in, search, patch one item (--record saves a cassette, --offline replays it)
.venv\Scripts\python.exe scripts\checkpoint.py

# Create the test dataset (items, part numbers, BOM links) in the collab space
.venv\Scripts\python.exe scripts\seed_items.py --yes

# Run the agent: dry run, then write proposals at confidence >= 0.5
.venv\Scripts\python.exe scripts\run_agent.py
.venv\Scripts\python.exe scripts\run_agent.py --apply

# Review proposals
.venv\Scripts\python.exe scripts\review.py
.venv\Scripts\python.exe scripts\review.py --approve <id> [--value "edited value"]
.venv\Scripts\python.exe scripts\review.py --reject <id>

# Score proposals and review decisions against the ground truth (offline)
.venv\Scripts\python.exe scripts\evaluate.py --out runs\eval.json
```

Phase 4 comparisons run offline on an in-memory tenant built from a dataset file, so every run starts from the
same blanks and nothing is written to the tenant:

```powershell
# Held-out data from the SolidWorks files (needs SolidWorks; read-only), then the dataset file
.venv\Scripts\python.exe scripts\extract_cad.py
.venv\Scripts\python.exe scripts\cad_to_dataset.py

# Rules and LLM on both datasets; LLM answers vary, so repeat them
.venv\Scripts\python.exe scripts\run_agent.py --dataset data\dataset.json
.venv\Scripts\python.exe scripts\run_agent.py --dataset data\dataset_cad.json
.venv\Scripts\python.exe scripts\run_agent.py --dataset data\dataset_cad.json --suggester llm --repeat 3
.venv\Scripts\python.exe scripts\compare.py --since 20261023 --out runs\compare.json
```

## Tests

```powershell
.venv\Scripts\python.exe -m pytest
```

All tests run offline. The agent tests use an in-memory tenant built from `data/dataset.json`; the client tests
use fake HTTP responses and a scrubbed recording of real calls.

## Evaluation data and first results

`data/dataset.json` holds 18 items in 3 assemblies with their true descriptions and part numbers. On 9 items,
12 fields are left blank in PLM for the agent to fill; the true values stay in the file as ground truth.

First live run (rule-based suggester, 15 September 2026):

| Measure | Result |
|---|---|
| Blank fields detected | 12/12 |
| Gaps with a proposal | 10/12 |
| Correct proposals (ignoring case and punctuation) | 6/10 |
| Correct at confidence ≥ 0.5 (written to PLM) | 5/5 |
| Correct below 0.5 (title expansion) | 1/5 |

These numbers are optimistic: the rules were written with this dataset in view.

`data/dataset_cad.json` is the held-out set, built by `cad_to_dataset.py` from the SolidWorks sample models (a hand
truck and an orbital sprinkler, 48 files). It has 17 known values blanked at random (seed 2026) as ground truth, and
39 fields with no CAD value, which are real gaps without ground truth. Rules, offline, 23 October 2026:

| Dataset | Graded gaps | Coverage | Correct | Written (confidence ≥ 0.5) |
|---|---|---|---|---|
| `dataset.json` (rules written for it) | 12 | 83% | 50% | 5, all correct |
| `dataset_cad.json` (held out) | 17 | 59% | 0% | 0 |

The rules do not transfer: they expect `API_..._` underscore titles and plain number sequences, while the CAD data
uses spaced names and `family-variant-revision` part numbers (`507-0702-00`). Their confidence stayed below 0.5,
so nothing wrong would have been written to PLM.

GPT-OSS-120B on Lehmus AI, 3 runs per dataset, offline, 23 October 2026 (`runs/compare-20261023.json`; mean, range):

| Suggester | Dataset | Accuracy | Close | Written (correct) | Brier |
|---|---|---|---|---|---|
| Rules | `dataset.json` | 50% | 67% | 5 (5) | 0.13 |
| GPT-OSS-120B | `dataset.json` | 47% (42-58%) | 75% (67-83%) | 10.7 (5.7) | 0.31 |
| Rules | `dataset_cad.json` | 0% | 0% | 0 (0) | 0.10 |
| GPT-OSS-120B | `dataset_cad.json` | 4% (0-6%) | 16% (6-24%) | 11 (0.7) | 0.52 |

"Close" counts descriptions sharing at least half their words with the truth. Brier is the squared error of the
confidence; always answering 0.5 scores 0.25. The model's descriptions are often close in meaning, but its confidence
does not separate right from wrong: at the 0.5 threshold it would write about 10 wrong values to PLM on the CAD data.
On CAD part numbers it guesses the same free number for many parts, which the duplicate check drops.

Most CAD descriptions are configuration-specific properties, not on the file's Custom tab: reading only the Custom
tab makes the sprinkler look almost empty. The source data has its own errors too (the upper bearing spring is
described as "Upper bearing - 22mm").

## Findings about the API

Verified on the tenant where it differs from the dseng 1.4.1 OpenAPI examples (details in `docs/spec-notes.md`):

- The cloud tenant rejects calls without a `?tenant=` query parameter.
- BOM links and where-used lookups need the tenant's 3DSpace URL as `source` and the full
  `/resources/v1/modeler/dseng/dseng:EngItem/{id}` path; the spec's `$3DSpace` examples are rejected.
- Creating several items in one call copies the previous item's part number onto items created without one.
- BOM children are returned in no particular order.
- Search and where-used are index based and lag a few minutes behind changes.
- Search responses omit empty attributes instead of returning empty strings.
- Reading material (`dsspec:Material`) returns 403 with the current roles.

## Repository layout

```
plm_client/   REST client: auth, session, Engineering calls, recording, generated models
agent/        snapshot, gap detection, suggesters, write-back and proposal log
scripts/      checkpoint, seed, run_agent, review, evaluate, compare, extract_cad, cad_to_dataset
data/         ground-truth datasets (Phase 3 and held-out CAD), CAD extract, ids of seeded items
runs/         agent run outputs, proposal log, evaluation reports
docs/         dseng 1.4.1 OpenAPI spec and verified API notes
tests/        offline tests and the scrubbed cassette
```
