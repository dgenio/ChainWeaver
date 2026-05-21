"""Entry-point discovery for community-contributed tools and flows (issue #130).

ChainWeaver follows the same plugin convention used by pytest, Sphinx,
Flake8, MkDocs, and many others — Python's standard
``[project.entry-points]`` table.  Third parties publish a package that
declares one or both of these groups:

.. code-block:: toml

    [project.entry-points."chainweaver.tools"]
    aws = "chainweaver_aws:get_tools"

    [project.entry-points."chainweaver.flows"]
    aws = "chainweaver_aws:get_flows"

Each referenced callable takes no arguments and returns a list of
:class:`~chainweaver.tools.Tool` (for ``chainweaver.tools``) or
:class:`~chainweaver.flow.Flow` / :class:`~chainweaver.flow.DAGFlow`
(for ``chainweaver.flows``).  Returning anything else, raising on
import, or raising inside the loader is treated as a misbehaving plugin
— by default a ``warning`` is logged and the offending entry is
silently skipped so the rest of the discovery loop continues.  Pass
``strict=True`` to raise :class:`PluginDiscoveryError` instead.

**Discovery is opt-in.**  Importing :mod:`chainweaver` does *not*
trigger plugin imports — too magical, hurts startup time, and would
leak third-party failures into core paths.  Callers must either:

- Call :func:`discover_tools` / :func:`discover_flows` explicitly, or
- Pass ``discover_plugins=True`` to :class:`~chainweaver.executor.FlowExecutor`
  / :class:`~chainweaver.registry.FlowRegistry` at construction time.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING, Any

from chainweaver.exceptions import PluginDiscoveryError

if TYPE_CHECKING:  # pragma: no cover — type-only references
    from chainweaver.flow import DAGFlow, Flow
    from chainweaver.tools import Tool


_TOOLS_GROUP = "chainweaver.tools"
_FLOWS_GROUP = "chainweaver.flows"

_logger = logging.getLogger("chainweaver.plugins")


def _entry_point_id(ep: EntryPoint) -> str:
    """Return a human-readable identifier for *ep* (``"<dist>:<name>"``)."""
    dist = getattr(ep, "dist", None)
    dist_name = getattr(dist, "name", None) if dist is not None else None
    if dist_name:
        return f"{dist_name}:{ep.name}"
    # ``EntryPoint.value`` is the ``"module:attr"`` target — useful when
    # the distribution is unknown (e.g., test fixtures).
    return f"{ep.value}:{ep.name}"


def _iter_entry_points(group: str) -> Iterable[EntryPoint]:
    """Yield every entry point registered under *group*.

    Wraps :func:`importlib.metadata.entry_points` with the group-keyword
    form that has been stable since Python 3.10.
    """
    return entry_points(group=group)


def _load_one(
    ep: EntryPoint,
    *,
    strict: bool,
    expected_types: tuple[type, ...],
    expected_label: str,
) -> list[Any]:
    """Resolve *ep*, call it, and validate the returned list.

    Any failure during ``ep.load()``, the loader call, or the return-type
    check funnels through the same path:

    - ``strict=True`` raises :class:`PluginDiscoveryError`.
    - ``strict=False`` (default) emits a warning and returns ``[]``.

    Args:
        ep: The entry point to resolve.
        strict: Whether to raise on failure instead of warn-and-skip.
        expected_types: Tuple of acceptable item types for ``isinstance``
            checks on the loader's return value (e.g. ``(Tool,)`` or
            ``(Flow, DAGFlow)``).
        expected_label: Human-readable label for the expected element
            type, used only in error messages.
    """
    ep_id = _entry_point_id(ep)

    def _fail(detail: str) -> list[Any]:
        if strict:
            raise PluginDiscoveryError(ep_id, detail)
        _logger.warning("Skipping plugin entry-point '%s': %s", ep_id, detail)
        return []

    try:
        loader = ep.load()
    except Exception as exc:
        return _fail(f"could not import loader ({type(exc).__name__}: {exc})")

    if not callable(loader):
        return _fail(f"entry point resolved to {type(loader).__name__}, expected a callable")

    try:
        result = loader()
    except Exception as exc:
        return _fail(f"loader raised {type(exc).__name__}: {exc}")

    if not isinstance(result, list):
        return _fail(f"loader returned {type(result).__name__}, expected list[{expected_label}]")

    bad = [item for item in result if not isinstance(item, expected_types)]
    if bad:
        return _fail(
            f"loader returned {len(bad)} non-{expected_label} item(s); "
            f"first offender: {type(bad[0]).__name__}"
        )

    return result


def discover_tools(
    *,
    group: str = _TOOLS_GROUP,
    strict: bool = False,
) -> list[Tool]:
    """Return every :class:`~chainweaver.tools.Tool` advertised under *group*.

    Args:
        group: Entry-point group name.  Defaults to ``"chainweaver.tools"``.
            Override only when wiring test fixtures.
        strict: When ``True``, a misbehaving plugin raises
            :class:`PluginDiscoveryError` and aborts discovery.  When
            ``False`` (the default), the offending entry is logged at
            ``WARNING`` and skipped so other plugins continue to load.

    Returns:
        A flat list of :class:`Tool` instances aggregated from every
        well-behaved entry point under *group*.

    Raises:
        PluginDiscoveryError: Only when *strict* is ``True`` and at
            least one plugin misbehaves.
    """
    # Imported lazily so ``import chainweaver.plugins`` is cheap and
    # never triggers a circular import via ``chainweaver.tools``.
    from chainweaver.tools import Tool

    tools: list[Tool] = []
    for ep in _iter_entry_points(group):
        tools.extend(_load_one(ep, strict=strict, expected_types=(Tool,), expected_label="Tool"))
    return tools


def discover_flows(
    *,
    group: str = _FLOWS_GROUP,
    strict: bool = False,
) -> list[Flow | DAGFlow]:
    """Return every :class:`~chainweaver.flow.Flow` or DAGFlow advertised under *group*.

    Args:
        group: Entry-point group name.  Defaults to ``"chainweaver.flows"``.
        strict: See :func:`discover_tools`.

    Returns:
        A flat list of :class:`Flow` / :class:`DAGFlow` instances.

    Raises:
        PluginDiscoveryError: Only when *strict* is ``True`` and at
            least one plugin misbehaves.
    """
    from chainweaver.flow import DAGFlow, Flow

    flows: list[Flow | DAGFlow] = []
    for ep in _iter_entry_points(group):
        flows.extend(
            _load_one(
                ep,
                strict=strict,
                expected_types=(Flow, DAGFlow),
                expected_label="Flow | DAGFlow",
            )
        )
    return flows
