from __future__ import annotations

import sys

from public_api_snapshot import (
    build_public_api_snapshot,
    load_public_api_snapshot,
)


def test_public_api_snapshot_matches_fixture() -> None:
    expected = load_public_api_snapshot()
    actual = build_public_api_snapshot()

    fixture_version = tuple(expected.get("python_version", [0, 0]))
    current_version = sys.version_info[:2]

    if fixture_version != current_version:
        # Cross-version: only compare __all__ (version-independent).
        assert actual["__all__"] == expected["__all__"], (
            "Public API __all__ changed. If intentional, run "
            "`python tests/scripts/regen_public_api.py` and commit the updated "
            "`tests/fixtures/public_api.json`.\n"
            f"  Added: {set(actual['__all__']) - set(expected['__all__'])}\n"
            f"  Removed: {set(expected['__all__']) - set(actual['__all__'])}"
        )
        # Also check symbol kinds and modules (version-independent).
        for name in actual["__all__"]:
            a_sym = actual["symbols"].get(name, {})
            e_sym = expected["symbols"].get(name, {})
            assert a_sym.get("kind") == e_sym.get("kind"), (
                f"Symbol '{name}' kind changed: {a_sym.get('kind')} vs {e_sym.get('kind')}"
            )
            assert a_sym.get("module") == e_sym.get("module"), (
                f"Symbol '{name}' module changed: {a_sym.get('module')} vs {e_sym.get('module')}"
            )
        return

    # Same version: full comparison.
    if actual != expected:
        a_syms = actual.get("symbols", {})
        e_syms = expected.get("symbols", {})
        diffs: list[str] = []
        if actual.get("__all__") != expected.get("__all__"):
            a_set = set(actual["__all__"])
            e_set = set(expected["__all__"])
            diffs.append(f"__all__ added: {a_set - e_set}")
            diffs.append(f"__all__ removed: {e_set - a_set}")
        for key in sorted(set(list(a_syms.keys()) + list(e_syms.keys()))):
            if a_syms.get(key) != e_syms.get(key):
                for field in set(
                    list(a_syms.get(key, {}).keys()) + list(e_syms.get(key, {}).keys())
                ):
                    av = a_syms.get(key, {}).get(field)
                    ev = e_syms.get(key, {}).get(field)
                    if av != ev:
                        diffs.append(f"{key}.{field}:\n  actual:   {av!r}\n  expected: {ev!r}")
        diff_text = "\n".join(diffs[:10])
        raise AssertionError(
            f"Public API snapshot changed (Python {current_version}).\n"
            f"If intentional, run `python tests/scripts/regen_public_api.py`.\n\n"
            f"Diff:\n{diff_text}"
        )
