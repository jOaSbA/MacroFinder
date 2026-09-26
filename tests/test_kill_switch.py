"""The kill switch. Milestone 30, PLAN-V2 section 7.

If a chain asks the project to stop, the author sets the repository variable
DATA_HALTED=true. The data job then scrapes nothing and republishes the last
manifest with status "halted" and a message; phones stop syncing and show it.
"""

import json

from bonusrank import appdb


def _manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "schema_version": appdb.SCHEMA_VERSION, "status": "ok",
        "generated_at": "2026-09-26T06:00:00+00:00",
        "full": {"file": "macrofinder-abc.sqlite", "version": "abc", "sha256": "x",
                 "bytes": 1, "products": 1},
        "deltas": [],
    }), encoding="utf-8")
    return path


def test_halting_keeps_the_assets_and_says_why(tmp_path):
    path = _manifest(tmp_path)
    out = appdb.halt_manifest(path, message="Op verzoek van een winkel gestopt.")
    assert out["status"] == "halted"
    assert out["message"] == "Op verzoek van een winkel gestopt."
    assert out["full"]["version"] == "abc"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "halted"


def test_halting_without_a_message_leaves_the_app_to_say_it(tmp_path):
    out = appdb.halt_manifest(_manifest(tmp_path), message=None)
    assert out["status"] == "halted"
    assert "message" not in out


def test_a_normal_build_is_ok_again():
    # write_manifest always writes "ok": the next run after DATA_HALTED is
    # cleared resumes by itself, with nothing to undo by hand.
    import inspect
    assert inspect.signature(appdb.write_manifest).parameters["status"].default == "ok"
