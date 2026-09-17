"""Resolve a Nuxt `__NUXT_DATA__` payload: JSON's devalue serialisation.

Milestone 7 (Jumbo). Nuxt embeds page state as a flat JSON array where every
object/array VALUE is an integer index into that same array, not a literal -
this is how it de-duplicates repeated values (every `false` in a big payload is
one shared index). `resolve(arr, i)` walks that graph back into ordinary nested
Python objects.

This is the documented, MIT-licensed `devalue` format (used broadly beyond
Nuxt), not a reverse-engineered one-off. The subset implemented here - plain
dicts, lists, and primitive leaves - is everything Jumbo's public pages emit;
Nuxt's rarer reducers (Map, Set, Date, custom classes, each wrapped as
`[TypeName, ...refs]`) are not needed and are left unresolved rather than
guessed at, since guessing here would look like a working parser while quietly
returning wrong data - the exact failure mode CLAUDE.md forbids for parsers.
"""

from __future__ import annotations

import re
from typing import Any

_NUXT_DATA_RE = re.compile(
    r'<script[^>]*\bid="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S
)


def extract_nuxt_data(html: str) -> str:
    """Pull the raw `__NUXT_DATA__` JSON text out of a server-rendered page."""
    match = _NUXT_DATA_RE.search(html)
    if not match:
        raise ValueError("no __NUXT_DATA__ script tag found - page shape has changed")
    return match.group(1)


def resolve(arr: list, index: int = 0, *, memo: dict[int, Any] | None = None) -> Any:
    """Rebuild the object at `arr[index]`, following every integer reference.

    Dict values and list elements are always references (never literals) in this
    format, so the walk is uniform. `memo` makes repeated and cyclic references
    safe and cheap - a payload this size reuses the same handful of primitives
    (mostly `false`/`null`/short strings) thousands of times.
    """
    memo = {} if memo is None else memo
    if index in memo:
        return memo[index]

    raw = arr[index]
    if isinstance(raw, dict):
        out: dict[str, Any] = {}
        memo[index] = out
        for key, ref in raw.items():
            out[key] = resolve(arr, ref, memo=memo) if isinstance(ref, int) else ref
        return out
    if isinstance(raw, list):
        out_list: list[Any] = []
        memo[index] = out_list
        for ref in raw:
            out_list.append(resolve(arr, ref, memo=memo) if isinstance(ref, int) else ref)
        return out_list

    # A primitive leaf: string, float, bool, or None. Ints are the one ambiguous
    # case - devalue stores them as their own leaf too, self-referencing by
    # coincidence for small values - but resolve() is never called on a leaf
    # except as someone else's reference, so returning it as-is is correct either way.
    memo[index] = raw
    return raw


# Vue/Nuxt reactivity wrappers: `[tag, innerRef]`. Resolving already turns the
# wrapped ref into real data: only the tag needs stripping to reach it. This is
# not a fixed whitelist of every devalue reducer, just the handful Nuxt itself
# emits for page state - a tag not in this set is left as a two-element list
# rather than guessed at.
_REACTIVITY_TAGS = {"ShallowReactive", "Reactive", "EmptyShallowReactive", "Ref", "ShallowRef"}


def unwrap(node: Any) -> Any:
    """Strip Vue reactivity wrappers so plain dict/list traversal works."""
    while (
        isinstance(node, list) and len(node) == 2
        and isinstance(node[0], str) and node[0] in _REACTIVITY_TAGS
    ):
        node = node[1]
    return node


def find_all(node: Any, key: str) -> list[Any]:
    """Every value found under `key` anywhere in a resolved tree, depth-first.

    For digging a specific field (e.g. a store's `promotions` list) out of a
    page shape that is not worth modelling in full - only what this adapter
    actually reads gets a real path.
    """
    found: list[Any] = []
    _walk(node, key, found)
    return found


def find_by_typename(node: Any, typename: str) -> list[dict]:
    """Every dict tagged `__typename: typename` anywhere in a resolved tree.

    Nuxt/GraphQL payloads carry `__typename` on every typed object, which is a
    far more stable anchor than a field name - Jumbo moved its unit-size field
    around between the listing and the detail page (see `adapters/jumbo.py`),
    but `__typename: "Product"` stayed put.
    """
    found: list[dict] = []
    _walk_typename(node, typename, found, set())
    return found


def _walk_typename(node: Any, typename: str, found: list[dict], seen: set[int]) -> None:
    node = unwrap(node)
    if isinstance(node, dict):
        if id(node) in seen:
            return
        seen.add(id(node))
        if node.get("__typename") == typename:
            found.append(node)
        for v in node.values():
            _walk_typename(v, typename, found, seen)
    elif isinstance(node, list):
        for item in node:
            _walk_typename(item, typename, found, seen)


def _walk(node: Any, key: str, found: list[Any]) -> None:
    node = unwrap(node)
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                found.append(unwrap(v))
            else:
                _walk(v, key, found)
    elif isinstance(node, list):
        for item in node:
            _walk(item, key, found)
