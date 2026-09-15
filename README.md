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
| 4. Evaluation | Score proposals against ground truth; rules vs. LLM comparison | In progress |

## How the agent works

1. **Snapshot**: search every Engineering Item in one collab space; fetch BOM children and where-used parents on demand.
2. **Gap detection** (plain code, no AI): list empty `description` and `partNumber` fields.
3. **Suggesters** propose a value with a confidence score and the evidence used:
   - *description by analogy*: copy the description of a same-family item whose title differs only in a variant token
     (`API_NUT_M8_ISO4032` "Hex nut M8 …" → `API_NUT_M6_ISO4032` "Hex nut M6 …")
   - *sibling part numbers*: fill the one number missing among the other parts in the same assembly
     (GRD-3001, GRD-3003, GRD-3004 → GRD-3002)
   - *title expansion*: low-confidence fallback built from the item title
   - An LLM suggester slot (`ClaudeSuggester`) shares the same interface and is not implemented yet.
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

These numbers are optimistic: the rules were written with this dataset in view. A held-out dataset and an
LLM-based suggester are the next steps for Phase 4.

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
scripts/      checkpoint, seed, run_agent, review, evaluate
data/         ground-truth dataset and the ids of seeded items
runs/         agent run outputs, proposal log, evaluation reports
docs/         dseng 1.4.1 OpenAPI spec and verified API notes
tests/        offline tests and the scrubbed cassette
```
