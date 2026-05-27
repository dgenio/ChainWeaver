"""Standard contrib tools: ``json_pluck`` and ``json_set``.

Demonstrates how the JSON-pointer-driven extract / mutate pair from
:mod:`chainweaver.contrib.tools` collapses a fistful of boilerplate
helpers down to a single ``pip install 'chainweaver[contrib]'``.

Run::

    python examples/contrib_pluck_and_set.py
"""

from __future__ import annotations

from chainweaver.contrib.tools import json_pluck, json_set

# ---------------------------------------------------------------------------
# json_pluck — extract by RFC-6901 JSON pointer
# ---------------------------------------------------------------------------

order = {
    "customer": {"id": 42, "name": "Alice"},
    "items": [{"sku": "abc-1", "qty": 2}, {"sku": "def-2", "qty": 5}],
}

# Top-level field.
customer_id = json_pluck.run({"data": order, "pointer": "/customer/id"})
print("customer_id =", customer_id)
# {'value': 42}

# Indexed into a list.
first_sku = json_pluck.run({"data": order, "pointer": "/items/0/sku"})
print("first_sku =", first_sku)
# {'value': 'abc-1'}

# ---------------------------------------------------------------------------
# json_set — return a new dict with a value placed at the given pointer
# ---------------------------------------------------------------------------

# Missing intermediate dicts are created on demand.
enriched = json_set.run(
    {"data": order, "pointer": "/customer/tier", "value": "premium"},
)
print("enriched customer =", enriched["data"]["customer"])
# {'id': 42, 'name': 'Alice', 'tier': 'premium'}

# Original is untouched — both tools are pure.
assert "tier" not in order["customer"]
print("original is unchanged:", order["customer"])
