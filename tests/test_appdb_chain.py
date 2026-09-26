"""Carrying deltas from one manifest to the next.

The data job runs twice a day and each run publishes a new build. If the
manifest only listed the newest delta, a phone that syncs once a day would
always be two builds behind and always download the full 24 MB. So each run
keeps the previous manifest's deltas and appends its own, as one chain ending
at the new build.
"""

from bonusrank.appdb import MAX_PUBLISHED_DELTAS, chain_deltas


def d(a, b):
    return {"from": a, "to": b, "file": f"delta-{a}-{b}.sqlite", "sha256": "x", "bytes": 1}


def test_new_delta_is_appended_to_the_carried_chain():
    carried = [d("v1", "v2"), d("v2", "v3")]
    out = chain_deltas(carried, [d("v3", "v4")], target="v4")
    assert [x["to"] for x in out] == ["v2", "v3", "v4"]


def test_an_unchanged_build_keeps_the_previous_chain():
    carried = [d("v1", "v2"), d("v2", "v3")]
    assert chain_deltas(carried, [], target="v3") == carried


def test_no_path_to_the_new_build_means_no_deltas():
    # A schema change refuses the new delta. The old ones lead somewhere the
    # new build isn't, so publishing them would only waste a phone's requests.
    carried = [d("v1", "v2"), d("v2", "v3")]
    assert chain_deltas(carried, [], target="v4") == []


def test_the_chain_is_capped_at_the_apps_hop_limit():
    versions = [f"v{i}" for i in range(20)]
    carried = [d(a, b) for a, b in zip(versions, versions[1:])]
    out = chain_deltas(carried, [], target="v19")
    assert len(out) == MAX_PUBLISHED_DELTAS
    assert out[-1]["to"] == "v19"
    assert all(x["to"] == y["from"] for x, y in zip(out, out[1:]))


def test_a_broken_link_cuts_the_chain_there():
    carried = [d("v1", "v2"), d("v5", "v6")]
    out = chain_deltas(carried, [d("v6", "v7")], target="v7")
    assert [x["from"] for x in out] == ["v5", "v6"]


def test_the_limit_matches_the_app():
    from pathlib import Path
    import re

    kt = (Path(__file__).resolve().parents[1]
          / "android/app/src/main/kotlin/com/macrofinder/app/data/sync/SyncPlan.kt")
    hops = int(re.search(r"const val MAX_DELTA_HOPS = (\d+)", kt.read_text("utf-8")).group(1))
    assert MAX_PUBLISHED_DELTAS == hops
