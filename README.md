# Agentic AI for PLM: attribute enrichment on 3DEXPERIENCE

Master's thesis project (University of Oulu). An agent finds missing attributes on Engineering Items in a
3DEXPERIENCE cloud tenant, proposes values from evidence in the product structure, and writes them back so a
human reviewer can approve or reject each one.

The integration uses only the public REST Web Services (`dseng` Engineering API) that come with a named-user
role. The Enterprise Integration Architect role and platform events are not available, so the agent **pulls**:
search → decide → write back.

```
AI agent (gap detection, suggesters)  →  Python REST client  →  3DEXPERIENCE public REST (dseng, dsrt routes)
          ↑ LLM: GPT-OSS-120B on Lehmus AI (University of Oulu)
```

## Status

| Phase | Scope | State |
|---|---|---|
| 1. Validate access | Postman calls against the Engineering API | Done |
| 2. REST client | 3DPassport login, CSRF, search, GET/PATCH, recorded offline replay | Done |
| 3. Agent logic | Gap detection, rule-based and LLM suggesters, `[PROPOSED]` write-back, review in a script or in a 3DEXPERIENCE route | Done; route review verified on the tenant |
| 4. Evaluation | Score proposals against ground truth; held-out CAD dataset; rules vs. LLM vs. LLM with evidence-based confidence | Runs done; results below |

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
     With `--confidence evidence` the model does not rate itself: it states its basis (*copied* from a near-identical
     item, a *pattern* among related items, *inferred*, *guess*) and the items it used; the code checks that those
     items exist and maps the basis to a fixed confidence on the rules' scale (0.8 / 0.7 / 0.3 / 0.1).
4. **Write-back for review**: descriptions are written as `[PROPOSED] value`, so reviewers see them in the
   3DEXPERIENCE app. Part numbers are identifiers, so they are only logged and written on approval. Every proposal
   and decision is appended to `runs/proposals.jsonl`.
5. **Review**: approve (optionally with an edited value) or reject (restores the old value). A field changed in PLM
   after the proposal was written is refused as a conflict. Two ways to review:
   - `review.py` on the command line;
   - **in 3DEXPERIENCE** (`review_route.py`): the agent creates a route (approval workflow) with one Approve task
     per proposal in the reviewer's task inbox. The reviewer approves or rejects there; approving with the comment
     `value: <text>` accepts a corrected value. `sync` reads the decisions and applies them. Verified on the
     tenant on 28 October 2026: an LLM proposal ("Plain washer M8 ISO 7089, zinc plated") was corrected in the task
     to "Flat washer M8 ISO 7089" and applied to the item.
   **Tool-using agent** (`--suggester agent`, `agent/agentic.py`): the LLM starts with the item, its empty field and
   the titles of its parents and children, and decides itself which evidence to gather with tools (`find_similar`,
   `get_siblings`, `get_item`, `get_parents`, `get_children`, `find_items`, `list_items`), at most 6 calls per gap, before it answers. Rules, answer format and confidence modes are the
   same as the fixed-context LLM, so the two differ only in who chooses the evidence. In evidence mode a source
   counts only if the agent actually looked at that item. Tools are declared as native function calls, with a
   plain JSON fallback for endpoints without tool support. Versions are labelled (`agent-v3:...`); v1 and v2 runs
   stay in the comparison.
6. **Release readiness** (`readiness.py`): before an assembly is released, walk its whole BOM and list every
   blocker: missing descriptions or part numbers, `[PROPOSED]` values nobody approved, proposals still pending
   review, part numbers used twice, cycles in the structure. Read-only; exit code 1 when not ready, and
   optionally a route task with the verdict in the reviewer's 3DEXPERIENCE inbox. It reports rather than blocks:
   changing the maturity state would need the lifecycle API.
7. **Duplicate detection** (`duplicates.py`): parts that already exist under another title or part number, either
   every candidate pair in the collab space or, before a part is created, the existing items it may duplicate
   (`--new "Hex bolt M8x25, zinc plated"`). Plain code, read-only: title and description words weighted by how
   rare they are in the collab space; size specs must agree (an M6 and an M8 nut are variants, not duplicates), a
   different material rules a pair out, and assemblies with the same children match whatever they are called.
   Every candidate comes with its reasons (shared words, same specs, same material, same children).
8. **3DDashboard widget** (`widget/`, served by `serve_widget.py`): the reviewer's side inside 3DEXPERIENCE, in
   the "Run your App" widget. Review tab (approve, edit and approve, reject, with the same conflict check as
   `review.py`), release readiness as a BOM tree, and duplicates with a "check before creating" box. The widget
   calls 3DSpace with the logged-in user's own session (WAFData): no credentials in the widget, and each user sees
   and changes only what their role allows. The local server only serves the files and the proposal log (part
   number proposals live only there) and records the decisions. The checks are a JavaScript port (`widget/core.js`)
   that a test compares with the Python on both datasets. Opened outside 3DDashboard, it runs on a dataset:
   the offline demo. Verified on the tenant on 4 November 2026: 19 items and 18 BOM links read with the user's
   session inside 3DDashboard.
9. **Continuous mode** (`watch_agent.py`): instead of one run over everything, the agent polls the collab space and
   handles only items that are new or changed since the last poll (it compares each item's `cestamp`; search lags
   a few minutes behind changes, so this is near-real-time at best). This is
   the stand-in for platform events: with the Enterprise Integration Architect role, an event handler would call
   the same entry point (`run(..., only={item_id})`) for the item named in the event.

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

# LLM with evidence-based confidence (Lehmus AI is reachable only from the university network or VPN)
.venv\Scripts\python.exe scripts\run_agent.py --suggester llm --confidence evidence --apply

# Only one item or field, e.g. for a demo
.venv\Scripts\python.exe scripts\run_agent.py --only API_ASM_GUARD --fields description --apply --min-confidence 0.3

# Continuous mode: poll every 5 minutes and handle only new or changed items (--baseline: only later changes)
.venv\Scripts\python.exe scripts\watch_agent.py [--baseline] [--interval 300] [--once] [--apply]

# Release readiness of an assembly (read-only; --route sends the verdict as a task, --yes creates it)
.venv\Scripts\python.exe scripts\readiness.py API_ASM_CONVEYOR_LINE [--out runs\readiness.json] [--route [--yes]]

# Duplicates (read-only): every candidate pair, or check a part before creating it (exit 1 = may exist)
.venv\Scripts\python.exe scripts\duplicates.py [--dataset data\dataset_cad.json]
.venv\Scripts\python.exe scripts\duplicates.py --new "Hex bolt M8x25, zinc plated" [--title T] [--material M]

# 3DDashboard widget: open https://localhost:8443/index.html once (accept the certificate), then paste the
# same URL into the "Run your App" widget (lite.html if index.html does not connect); ?tab=readiness opens a tab
# (works for the offline demo; 3DDashboard cannot frame localhost, so for live use build single-file pages and
# host them on HTTPS, e.g. https://abdurrehman994.github.io/plm-agent-widget/index.html)
.venv\Scripts\python.exe scripts\serve_widget.py [--port 8443]
.venv\Scripts\python.exe scripts\build_widget.py      # widget/dist/: self-contained pages to host
.venv\Scripts\python.exe scriptsuild_widget.py                    # widget/dist/: self-contained pages to host

# Review proposals on the command line...
.venv\Scripts\python.exe scripts\review.py
.venv\Scripts\python.exe scripts\review.py --approve <id> [--value "edited value"]
.venv\Scripts\python.exe scripts\review.py --reject <id>

# ...or in 3DEXPERIENCE: a route with one Approve task per proposal, then apply the decisions
.venv\Scripts\python.exe scripts\review_route.py create --yes
.venv\Scripts\python.exe scripts\review_route.py sync --yes
.venv\Scripts\python.exe scripts\review_route.py delete <route id> --yes

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
.venv\Scripts\python.exe scripts\run_agent.py --dataset data\dataset_cad.json --suggester llm --confidence evidence --repeat 3
.venv\Scripts\python.exe scripts\compare.py --since 20261023 --out runs\compare.json

# Material (offline only: dsspec:Material returns 403 in the tenant), and one row per field
.venv\Scripts\python.exe scripts\run_agent.py --dataset data\dataset_cad.json --fields material
.venv\Scripts\python.exe scripts\compare.py --since 20261029 --by-field

# Wider evaluation: the same CAD values blanked in 10 random patterns instead of one
.venv\Scripts\python.exe scripts\sweep.py [--seeds 10] [--suggester llm] [--out runs\sweep.json]

# Tool-using agent: the same LLM gathers its own evidence (compare with --suggester llm on the same datasets)
.venv\Scripts\python.exe scripts\run_agent.py --dataset data\dataset.json --suggester agent --confidence evidence --repeat 3
.venv\Scripts\python.exe scripts\run_agent.py --dataset data\dataset_cad.json --suggester agent --confidence evidence --repeat 3

# Which confidence threshold to write at: chosen on dataset.json, tested unchanged on the CAD data
.venv\Scripts\python.exe scripts\threshold.py --since 20261023 --select dataset.json

# Calibration: confidence against accuracy, per basis, and whether a learned mapping transfers
.venv\Scripts\python.exe scripts\calibration.py --since 20261023 --suggester agent-v3 --suggester llm: --suggester rules [--by-field] [--close] [--plot runs\reliability.png] [--out runs\calibration.json]
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

### Material and several blank patterns (29 October 2026)

Material is a `dsspec:Material` relationship that the current roles cannot read (403), so it is evaluated offline
only: `cad_to_dataset.py` now reads SolidWorks' Material property (19 parts) and blanks 6 of them with a separate
random stream, so the description and part number blanks, and every earlier run, are unchanged. The rule
(`sibling-material`) proposes the material most other parts of the same assembly have and never proposes one for an
assembly; it was written before any run on the CAD data.

`dataset_cad.json` is one draw of which values are blanked. `sweep.py` repeats the rules over 10 draws (seeds
2026-2035, 30% blanked; mean and range):

| Field | Graded gaps | Coverage | Accuracy | Written (correct) | Brier |
|---|---|---|---|---|---|
| description | 9.6 (8-12) | 100% | 0% | 0 (0) | 0.09 |
| part number | 7.4 (5-9) | 7% (0-29%) | 0% | 0 (0) | 0.16 |
| material | 6 | 93% (67-100%) | 65% (50-83%) | 1.8 (1) | 0.29 |

The single-draw result (rules do not transfer to the CAD data for descriptions and part numbers) holds over all ten
draws. Material is where structure helps: parts of one assembly often share a material. Its confidence is not yet
calibrated (Brier above 0.25), so at the 0.5 threshold about half of the written materials would be wrong. The LLM
has not been run on material yet (Lehmus AI needs the university network).

### Choosing the confidence threshold (29 October 2026)

`threshold.py` replaces the fixed 0.5 with a threshold chosen from data: the lowest one at which no run writes a
wrong value. It is chosen on `dataset.json` and applied unchanged to the CAD data (description and part number;
mean per run over repeats):

| Suggester | Threshold (no wrong write on `dataset.json`) | Written there | CAD: written (wrong) | At 0.5 on CAD: written (wrong) |
|---|---|---|---|---|
| Rules | 0.60 | 5.0 | 0 (0) | 0 (0) |
| GPT-OSS-120B, own confidence | 0.93 | 2.0 | 0 (0) | 10.8 (10.0) |
| GPT-OSS-120B, evidence-based confidence | 0.70 | 4.0 | 2.2 (2.0) | 2.2 (2.0) |

The model's own confidence needs a threshold of 0.93 before it stops writing wrong values, and then it writes
almost nothing. Evidence-based confidence is safe at 0.70 on the data it was designed on, and cuts wrong writes on the
CAD data from 10 to 2 per run, but not to zero: a threshold chosen on one product structure does not guarantee
safety on another. Wrong writes are still reviewed before they count, but this is the measure to improve.

Most CAD descriptions are configuration-specific properties, not on the file's Custom tab: reading only the Custom
tab makes the sprinkler look almost empty. The source data has its own errors too (the upper bearing spring is
described as "Upper bearing - 22mm").

### Calibration (5 November 2026)

`calibration.py` measures how well each suggester's confidence matches how often it is right, from the run files
(offline; `--out runs/calibration.json` keeps the reliability bins for a diagram). Graded proposals, repeats pooled:

| Suggester | Dataset | Proposals | Mean confidence | Accuracy | ECE |
|---|---|---|---|---|---|
| GPT-OSS-120B, own confidence | `dataset.json` | 42 | 0.84 | 55% | 0.30 |
| GPT-OSS-120B, own confidence | `dataset_cad.json` | 43 | 0.75 | 7% | **0.68** |
| GPT-OSS-120B, evidence-based | `dataset.json` | 30 | 0.47 | 57% | 0.12 |
| GPT-OSS-120B, evidence-based | `dataset_cad.json` | 43 | 0.38 | 12% | 0.27 |
| Tool-using agent v3, evidence-based | `dataset.json` | 65 | 0.57 | 54% | 0.18 |
| Tool-using agent v3, evidence-based | `dataset_cad.json` | 48 | 0.59 | 25% | 0.34 |

ECE (expected calibration error) is the gap between confidence and accuracy, averaged over bins of width 0.2; 0 is
perfect. The model's own confidence is the worst: on the CAD data it is 75% sure on average and 7% right.
The fixed evidence mapping (0.8 / 0.7 / 0.3 / 0.1) was chosen with `dataset.json` in view, like the rules, so its
calibration there is optimistic; the CAD data is the fair test of it.

Accuracy per stated basis, tool-using agent v3, descriptions (`--by-field`; gaps = distinct blank fields, each
answered in 4-6 repeated runs):

| Basis (confidence given) | `dataset.json` | `dataset_cad.json` |
|---|---|---|
| copied (0.8) | 95% of 19 answers, 4 gaps | 46% of 13 answers, 6 gaps (95%: 0-86%) |
| pattern (0.7) | 0% of 4 answers, 3 gaps | 25% of 8 answers, 4 gaps |
| inferred (0.3) | 4% of 24 answers, 5 gaps (0-12%) | 0% of 15 answers, 5 gaps (0-60%) |

**How much data this is.** A gap answered in six repeated runs is one sample, not six: the repeats share the item,
the evidence and mostly the answer. The intervals are therefore a bootstrap over gaps (whole gaps resampled with all
their repeats; the rule of three where every gap has the same outcome), and none is given below 5 gaps. Counted
this way the evaluation rests on 10-16 gaps per suggester and dataset, and most per-basis cells on 2-6. Two
differences are clear at this size: the self-rated LLM is badly calibrated on the CAD data (ECE 0.68, 95%
0.54-0.77), and evidence-based confidence is better calibrated there (0.27, 0.10-0.43: the intervals do not
overlap). Whether the tool-using agent is worse calibrated on the CAD data than on `dataset.json` (ECE 0.34 against
0.18) is not settled: the intervals overlap. More gaps, not more repeats, would settle it.

**Descriptions and part numbers** (`--by-field`) fail differently. On `dataset.json` part numbers are the easy field
(89-100% right: they follow the assembly's number sequence) and descriptions the hard one (40-50%). On the CAD data
both are mostly wrong, and part numbers are the riskier: the agent's "pattern" part numbers (`507-0802-00` for
`507-0702-00`) are given 0.7 and right 36% of the time, and a wrong identifier is harder for a reviewer to spot than
a wrong description. A threshold chosen on `dataset.json` writes 64-86% wrong part numbers on the CAD data, which
supports the existing rule that part numbers are never written without approval. `runs/reliability-by-field.png`
shows the four panels.

The basis ranks the answers in the same order on both datasets (copied > pattern > inferred), and "inferred" is
almost never right on either: it separates well. What does not transfer is the level: the same basis is right half
as often on the CAD data. So learning the basis-to-confidence mapping on one dataset and applying it to the other
does not help (`calibration.py` table 3: ECE on the test data 0.33 learned against 0.34 fixed, and worse in the
other direction).

A threshold that is safe on one dataset is not safe on the other. With 50+ proposals a single wrong answer makes the
strict "no wrong write" threshold write nothing, so table 3 also chooses a tolerant one: the lowest threshold whose
written values are at most 10% wrong on the training data (`--max-wrong-rate`). Chosen on `dataset.json` and applied
unchanged to the CAD data:

| Suggester | Mapping | Tolerant threshold | CAD: written per run | CAD: wrong per run | Share wrong |
|---|---|---|---|---|---|
| Tool-using agent v3, evidence-based | fixed | 0.80 | 3.2 | 1.8 | 54% |
| Tool-using agent v3, evidence-based | learned | 0.90 | 3.2 | 1.8 | 54% |
| LLM, evidence-based | fixed | 0.70 | 2.2 | 2.0 | 89% |

At most 10% wrong where the threshold was chosen, 54-89% wrong where it was applied.

The result does not depend on exact matching being strict. With `--close` (a description sharing at least half its
words with the truth counts as correct, closer to what a reviewer would accept after a small edit), the
self-rated LLM is well calibrated on `dataset.json` (ECE 0.06) and badly on the CAD data (0.52); the evidence-based
modes go from under-confident on `dataset.json` (confidence 0.47-0.57 against 83-91% close) to over-confident on the
CAD data. Calibration measured on one product structure does not carry over to another, under either measure.

`--plot runs/reliability.png` draws the reliability diagram (`runs/reliability.png`, exact match;
`runs/reliability-close.png`, close match), for the thesis suggesters with
`--suggester agent-v3 --suggester llm: --suggester rules`.

A first look at why: on `dataset.json`, 18 of 19 "copied" answers are correct, but only one is a literal copy of a
source item; the others adapt it (Hex nut M8 -> M6). A check that the proposed value literally equals a source's
value therefore cannot verify the claim; it has to recognise a variant swap, as the `description-analogy` rule
does. On the CAD data many wrong "copied" and "pattern" answers are close paraphrases ("Sprinkler rotation
adjuster" for "Rotation Adjuster") or a part number guessed from a family pattern.

### Duplicate detection (4 November 2026)

There are no known duplicates in the datasets, so `duplicates.py --plant N` adds them: N parts created a second
time with no part number and no BOM place, the description lowercased with its last detail dropped, and every second
copy given a title that says nothing (`NEW PART A`), so only its description can match. 6 copies, 10 seeds (mean, min):

| Threshold | `dataset.json`: recall | precision | `dataset_cad.json`: recall | precision |
|---|---|---|---|---|
| 0.4 | 100% (100%) | 97% (86%) | 100% (100%) | 34% (30%) |
| 0.5 (default) | 100% (100%) | 100% (100%) | 100% (100%) | 41% (35%) |
| 0.6 | 48% (33%) | 100% (100%) | 100% (100%) | 44% (38%) |

0.5 is the highest threshold that finds every planted copy on `dataset.json`, which has no other duplicates: its M6
and M8 nuts and bolts share every word but the size and are correctly not reported. The CAD precision counts real
near-duplicates as wrong, because they were not planted: without planting, the detector reports 6 pairs in the CAD
data at 0.5, and 4 are worth a reviewer's look:
- `SWC-Gasket sprinkler` / `SWC-Gasket-jet sprinkler`: both "Base gasket" (506-0601-00, 506-0702-00);
- `Lower Pipe` / `Short.Pipe`: both `1 1/4" STANDARD WEIGHT PIPE` (the 1" handle pipe is kept apart);
- `SWC-Upper Washer` / `SWC-Washer-Swingarm`: brass washers, 23 mm;
- `SWC-Spring-upper bearing` / `SWC-Upper Bearing`: the spring is described as "Upper bearing - 22mm", an error in
  the source data found this way.
The other 2 are welds next to the parts they join (`Axle.Support` / `Weld.Axle.Support`, the long and short brace
welds): items with no description match on title words alone. Planted copies of the short CAD descriptions are
easy to find (recall stays 100% up to 0.9); the measure to improve is precision on real data.

## Findings about the API

Verified on the tenant where it differs from the dseng 1.4.1 OpenAPI examples (details in `docs/spec-notes.md`):

- The cloud tenant rejects calls without a `?tenant=` query parameter.
- BOM links and where-used lookups need the tenant's 3DSpace URL as `source` and the full
  `/resources/v1/modeler/dseng/dseng:EngItem/{id}` path; the spec's `$3DSpace` examples are rejected.
- Creating several items in one call copies the previous item's part number onto items created without one.
- BOM children are returned in no particular order.
- Search and where-used are index based and lag a few minutes behind changes.
- Search responses omit empty attributes instead of returning empty strings.
- Reading material (`dsspec:Material`) returns 403 with the current roles, so material gaps are evaluated offline only
  (`run_agent.py --dataset ... --fields material`); writing material back needs a role with access to it.

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
