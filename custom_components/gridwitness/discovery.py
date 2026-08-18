"""Auto-discovery of contributable entities by device_class, with phase grouping.

Buckets the user's sensor entities into GridWitness channels, infers L1/L2/L3 phase from
entity_id / friendly name, and proposes a default mapping the config flow renders for
confirmation or override. Frequency is treated as node-global (one entity, phase 1p).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONSENT_GROUPS, DEVICE_CLASS_CHANNELS, GROUP_DEVICE_CLASSES

_PHASE_TOKENS = [
    (re.compile(r"(?:^|[_\s])(?:l1|phase[_\s]?1|phase[_\s]?a|ph_?a)(?:$|[_\s])", re.I), "L1"),
    (re.compile(r"(?:^|[_\s])(?:l2|phase[_\s]?2|phase[_\s]?b|ph_?b)(?:$|[_\s])", re.I), "L2"),
    (re.compile(r"(?:^|[_\s])(?:l3|phase[_\s]?3|phase[_\s]?c|ph_?c)(?:$|[_\s])", re.I), "L3"),
]


def _infer_phase(*texts: str | None) -> str:
    for text in texts:
        if not text:
            continue
        for rx, phase in _PHASE_TOKENS:
            if rx.search(text):
                return phase
    return "1p"


@dataclass
class Candidate:
    entity_id: str
    channel: str
    phase: str
    device_class: str
    name: str


@dataclass
class Discovery:
    # group name -> list of candidate entities
    groups: dict[str, list[Candidate]] = field(default_factory=dict)

    def has_any(self) -> bool:
        return any(self.groups.values())


def _device_class_of(hass: HomeAssistant, entity_id: str, entry) -> str | None:
    state = hass.states.get(entity_id)
    if state is not None:
        dc = state.attributes.get("device_class")
        if dc:
            return dc
    if entry is not None:
        return entry.device_class or entry.original_device_class
    return None


def discover(hass: HomeAssistant) -> Discovery:
    """Return discovered candidates grouped by consent group."""
    registry = er.async_get(hass)
    group_of: dict[str, str] = {}
    for grp, classes in GROUP_DEVICE_CLASSES.items():
        for c in classes:
            group_of[c] = grp

    result = Discovery(groups={g: [] for g in CONSENT_GROUPS})

    for entry in registry.entities.values():
        if entry.disabled or entry.domain != "sensor":
            continue
        dc = _device_class_of(hass, entry.entity_id, entry)
        if not dc:
            continue
        channel = DEVICE_CLASS_CHANNELS.get(dc)
        group = group_of.get(dc)
        if not channel or not group:
            continue
        name = entry.name or entry.original_name or entry.entity_id
        # frequency is node-global -> always phase 1p; others infer from id/name
        phase = "1p" if channel == "frequency_hz" else _infer_phase(entry.entity_id, name)
        result.groups[group].append(
            Candidate(entity_id=entry.entity_id, channel=channel, phase=phase,
                      device_class=dc, name=name)
        )
    return result


def propose_mapping(discovery: Discovery) -> dict[str, list[dict[str, str]]]:
    """Default channel -> [{entity_id, phase}] mapping from discovery.

    For frequency, pick a single node-global entity. For the rest, keep all discovered candidates so
    a 3-phase meter maps L1/L2/L3 automatically.
    """
    mapping: dict[str, list[dict[str, str]]] = {}
    for candidates in discovery.groups.values():
        for cand in candidates:
            if cand.channel == "frequency_hz" and "frequency_hz" in mapping:
                continue  # only one frequency entity
            mapping.setdefault(cand.channel, []).append(
                {"entity_id": cand.entity_id, "phase": cand.phase}
            )
    return mapping
