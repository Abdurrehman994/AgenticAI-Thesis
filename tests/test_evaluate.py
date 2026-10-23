from agent.writeback import ProposalLog, approve, reject
from scripts.evaluate import collect, ground_truth, normalize, score, summarize
from scripts.run_agent import run


def test_normalize_ignores_case_and_punctuation():
    assert normalize("Guard hinge, aluminium") == normalize("guard  hinge aluminium")


def test_score():
    assert score("Hex nut M6", "Hex nut M6") == {"exact": True, "normalized": True, "close": True, "overlap": 1.0}
    assert score("Guard assembly", "Safety guard assembly") == {"exact": False, "normalized": False, "close": True, "overlap": 0.67}
    assert not score("Base plate for sprinkler assembly", "Base Mount Assembly")["close"]  # overlap 0.33


def test_close_does_not_apply_to_part_numbers():
    # 503-0601-00 and 502-0601-00 share two of three tokens, but a part number is right or wrong
    assert score("503-0601-00", "502-0601-00", "description")["close"]
    assert not score("503-0601-00", "502-0601-00", "partNumber")["close"]


def test_rules_baseline_on_dataset(tenant, dataset, tmp_path):
    log = ProposalLog(tmp_path / "proposals.jsonl")
    run(tenant, collabspace="API_development", apply=True, log=log)
    pending = {p["title"]: p for p in log.pending() if p["field"] == "description"}
    log.append(approve(tenant, pending["API_NUT_M6_ISO4032"]))
    log.append(reject(tenant, pending["API_ROLLER_IDLER_D50"]))
    # This run no longer lists gaps awaiting review; the evaluation takes those from the log
    later = run(tenant, collabspace="API_development", log=log)

    truth = ground_truth(dataset)
    summary = summarize(collect({"results": later}, log.proposals(), truth), truth)

    assert (summary["gaps_found"], summary["missed_blanks"]) == (12, [])
    overall = summary["overall"]
    assert (overall["proposals"], overall["exact"], overall["normalized"]) == (10, 5, 6)
    assert summary["review"] == {"approved": 1, "rejected": 1, "pending": 3, "not written": 5}
    assert (summary["approved_correct"], summary["rejected_but_correct"]) == (1, 1)
