"""The devalue resolver. Milestone 7 (Jumbo's `__NUXT_DATA__`).

Nuxt encodes page state as a flat array where every dict value and list element
is an integer index into that same array, not a literal - the documented
`devalue` format. These tests pin the resolver against small hand-built arrays
of that exact shape, plus the reactivity-wrapper unwrapping Nuxt's own payload
needs on top of it.
"""

from __future__ import annotations

import pytest

from bonusrank.parsers.devalue import extract_nuxt_data, find_all, find_by_typename, resolve, unwrap


def test_resolves_a_flat_dict():
    # {"a": "x", "b": "y"} encoded as devalue: index 0 is the dict, referencing
    # string leaves at 1 and 2.
    arr = [{"a": 1, "b": 2}, "x", "y"]
    assert resolve(arr, 0) == {"a": "x", "b": "y"}


def test_resolves_nested_lists_and_dicts():
    arr = [
        {"items": 1},
        [2, 3],
        {"name": 4},
        {"name": 5},
        "first",
        "second",
    ]
    assert resolve(arr, 0) == {"items": [{"name": "first"}, {"name": "second"}]}


def test_deduplicated_values_resolve_to_the_same_content():
    """The whole point of devalue: a repeated `false` is one shared index."""
    arr = [{"a": 1, "b": 2}, {"active": 3}, {"active": 3}, False]
    root = resolve(arr, 0)
    assert root["a"]["active"] is False
    assert root["b"]["active"] is False


def test_cyclic_references_do_not_infinite_loop():
    # index 0 is a dict whose "self" field points back at index 0.
    arr = [{"self": 0}]
    root = resolve(arr, 0)
    assert root["self"] is root


def test_primitives_pass_through_untouched():
    arr = [{"n": 1, "b": 2, "s": 3, "none": 4}, 42, True, "hi", None]
    assert resolve(arr, 0) == {"n": 42, "b": True, "s": "hi", "none": None}


# -- reactivity wrappers -----------------------------------------------------

def test_unwrap_strips_a_shallow_reactive_wrapper():
    assert unwrap(["ShallowReactive", {"x": 1}]) == {"x": 1}


def test_unwrap_leaves_an_ordinary_two_element_list_alone():
    assert unwrap(["a", "b"]) == ["a", "b"]


def test_unwrap_is_idempotent_on_plain_values():
    assert unwrap({"a": 1}) == {"a": 1}
    assert unwrap(None) is None


# -- traversal helpers --------------------------------------------------------

def test_find_all_collects_every_matching_key_depth_first():
    root = {"a": {"promotions": [1, 2]}, "b": {"c": {"promotions": [3]}}}
    assert find_all(root, "promotions") == [[1, 2], [3]]


def test_find_all_unwraps_reactivity_markers_along_the_way():
    root = ["ShallowReactive", {"promotions": ["ShallowReactive", [1]]}]
    assert find_all(root, "promotions") == [[1]]


def test_find_by_typename_finds_every_tagged_object_regardless_of_field_name():
    root = {
        "a": {"__typename": "Product", "id": 1},
        "b": [{"__typename": "Product", "id": 2}, {"__typename": "Other"}],
    }
    found = find_by_typename(root, "Product")
    assert sorted(p["id"] for p in found) == [1, 2]


def test_find_by_typename_does_not_loop_on_a_cycle():
    node = {"__typename": "Product", "id": 1}
    node["self"] = node
    assert find_by_typename(node, "Product") == [node]


# -- extracting the payload out of a page ------------------------------------

def test_extract_nuxt_data_pulls_the_script_contents():
    html = '<html><body><script id="__NUXT_DATA__" type="application/json">[1,2]</script></body></html>'
    assert extract_nuxt_data(html) == "[1,2]"


def test_extract_nuxt_data_raises_when_the_tag_is_missing():
    with pytest.raises(ValueError, match="__NUXT_DATA__"):
        extract_nuxt_data("<html><body>no data here</body></html>")


# -- EmptyRef (milestone 16) ---------------------------------------------------

def test_an_empty_ref_carries_a_json_string_not_the_value():
    """The one reactivity tag whose payload is encoded rather than resolved.

    Found on Jumbo's `/producten/` page past the last offset, where `count`
    comes back as `["EmptyRef", "0"]` instead of `["Ref", 17062]`. Treating it
    like the others hands the caller the string '0'; not recognising it at all
    leaves the whole two-element list in place, which is what ended a 712-page
    crawl 18 pages from the end with a TypeError from `int()`.
    """
    assert unwrap(["EmptyRef", "0"]) == 0
    assert unwrap(["EmptyRef", '""']) == ""
    assert unwrap(["EmptyRef", "null"]) is None


def test_an_unrecognised_tag_is_still_left_alone():
    """The existing promise: a tag outside the known set is not guessed at."""
    assert unwrap(["SomethingNew", "payload"]) == ["SomethingNew", "payload"]


def test_a_malformed_empty_ref_payload_is_unknown_rather_than_a_crash():
    assert unwrap(["EmptyRef", "not json"]) is None
