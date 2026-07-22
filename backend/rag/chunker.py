"""Turns loaded documents/incidents into embeddable chunks.

CLAUDE.md §7.2: static docs get ~300-token overlapping chunks (approximated
here by word count, since chunking doesn't need to be tied to any specific
model's tokenizer — the embedder applies its own tokenization downstream).

CLAUDE.md §7.3: each incident stage becomes its own chunk, carrying BOTH its
narrative text (embedded normally, for textual/semantic lookup) AND its
fast+slow numeric window pair (each window separately serialized to a short
templated text description and embedded, for the window-similarity
retrieval CLAUDE.md §7.4 describes as an ANN search over fast/slow window
vectors, not a numeric-only algorithm). See rag/embedder.py and
database/vector_store.py for how these three text streams end up in three
separate collections.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..simulation.models import SimulationRecord, XMEASVector, XMVVector
from ..simulation.synthetic_sensors import SyntheticSensorBaseline
from ..simulation.tep.constants import BASE_CASE_XMV
from ..simulation.tep.reference_data import compute_base_case_xmeas
from .loaders.document_loader import RawDocument
from .loaders.incident_loader import IncidentDefinition
from .windowing import WindowPair, window_pair_at

CHUNK_SIZE_WORDS = 300
CHUNK_OVERLAP_WORDS = 50

# A representative subset of channels summarized in a window's text
# description — the full 41+12+3 fields would be too verbose to embed
# meaningfully; these are the channels the seed incidents' narratives
# actually reason about.
WINDOW_SUMMARY_FIELDS = [
    ("xmeas", "reactor_pressure_kpa", "kPa"),
    ("xmeas", "reactor_level_pct", "%"),
    ("xmeas", "reactor_temperature_c", "C"),
    ("xmeas", "separator_pressure_kpa", "kPa"),
    ("xmeas", "stripper_level_pct", "%"),
    ("xmeas", "compressor_work_kw", "kW"),
    ("xmeas", "reactor_cw_outlet_temp_c", "C"),
    ("xmeas", "separator_cw_outlet_temp_c", "C"),
    ("xmeas", "product_g_mol_pct", "mol%"),
    ("xmeas", "product_h_mol_pct", "mol%"),
    ("xmv", "reactor_cw_flow_valve_pct", "%"),
    ("xmv", "compressor_recycle_valve_pct", "%"),
    ("xmv", "a_feed_flow_valve_pct", "%"),
    ("synthetic", "methane_ppm", "ppm"),
    ("synthetic", "vibration_mm_s", "mm/s"),
    ("synthetic", "valve_health_pct", "%"),
]


@dataclass
class DocumentChunk:
    chunk_id: str
    source_type: str  # "sop" | "msds" | "incident_narrative"
    source_name: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class WindowChunk:
    chunk_id: str  # shared with the DocumentChunk this window was derived from
    window_kind: str  # "fast" | "slow"
    text: str
    metadata: dict = field(default_factory=dict)


def chunk_static_text(
    text: str, source_type: str, source_name: str, metadata: dict | None = None,
    chunk_size_words: int = CHUNK_SIZE_WORDS, overlap_words: int = CHUNK_OVERLAP_WORDS,
) -> list[DocumentChunk]:
    words = text.split()
    if not words:
        return []
    metadata = metadata or {}
    chunks: list[DocumentChunk] = []
    start = 0
    part = 0
    step = max(1, chunk_size_words - overlap_words)
    while start < len(words):
        piece = words[start : start + chunk_size_words]
        chunk_text = " ".join(piece)
        chunks.append(
            DocumentChunk(
                chunk_id=f"{source_name}::part{part}",
                source_type=source_type,
                source_name=source_name,
                text=chunk_text,
                metadata=metadata,
            )
        )
        part += 1
        start += step
    return chunks


def chunk_raw_document(doc: RawDocument, source_type: str, metadata: dict | None = None) -> list[DocumentChunk]:
    return chunk_static_text(doc.text, source_type=source_type, source_name=doc.source_name, metadata=metadata)


def _field(record: SimulationRecord, group: str, name: str):
    return getattr(getattr(record, group), name)


# Different channel groups have very different natural noise levels: xmv
# (valve/actuator positions) are actively driven by PI control loops and
# routinely swing several percentage points during completely normal
# operation, while xmeas (process measurements) drift far more slowly and
# passively. Applying one blanket threshold to both was measurably wrong:
# it caused ordinary valve control noise to get labeled a "sharp deviation"
# purely because it happened to be a valve channel, discovered empirically
# when it made a genuinely fault-free held-out window's text resemble the
# reactor_cw_valve_stiction incident (whose whole signature IS valve
# erraticism). synthetic sensors share xmeas's threshold — Phase 1 stubs
# have zero variance today, but the physical quantities they proxy
# (methane concentration, vibration) behave like passive measurements, not
# actuator positions.
_THRESHOLDS = {
    "xmeas": {"relative": 0.005, "absolute_floor": 0.01},
    "xmv": {"relative": 0.05, "absolute_floor": 3.0},
    "synthetic": {"relative": 0.005, "absolute_floor": 0.01},
}


def _threshold_for(group: str, reference_value: float) -> float:
    cfg = _THRESHOLDS[group]
    return max(abs(reference_value) * cfg["relative"], cfg["absolute_floor"])


# Published Downs & Vogel base-case operating point, computed once (not
# hardcoded — see reference_data.py) — the reference every window's
# deviation is described against. See window_to_text's docstring for why
# deviation-from-baseline turned out to matter more than the within-window
# delta alone.
_BASELINE_XMEAS = XMEASVector.from_array(compute_base_case_xmeas())
_BASELINE_XMV = XMVVector.from_array(BASE_CASE_XMV)
_BASELINE_SYNTHETIC = SyntheticSensorBaseline()
_BASELINE_LOOKUP = {"xmeas": _BASELINE_XMEAS, "xmv": _BASELINE_XMV, "synthetic": _BASELINE_SYNTHETIC}


def _baseline_value(group: str, name: str) -> float:
    return getattr(_BASELINE_LOOKUP[group], name)


def _describe_change(group: str, first_value: float, delta: float) -> str:
    """Qualitative direction+magnitude description of a change, e.g.
    'rising sharply' / 'stable' / 'falling slightly'.

    Raw numeric deltas turned out to be a poor retrieval signal for BOTH
    halves of hybrid search: bge-small's embedding is dominated by the
    surrounding boilerplate template text and barely moves for different
    numeric content (empirically, even an all-zero-delta synthetic window
    scored >0.98 cosine similarity against real incident windows); and
    BM25's tokenizer used to split decimals at '.' (fixed separately in
    bm25_index.py), producing near-unique fragments that almost never
    coincided between independent noise realizations of the same trend.
    Qualitative words give both retrieval halves something meaningful to
    actually match on.
    """
    threshold = _threshold_for(group, first_value)
    if abs(delta) < threshold:
        return "stable"
    ratio = abs(delta) / threshold
    magnitude = "slightly" if ratio < 3 else ("moderately" if ratio < 8 else "sharply")
    direction = "rising" if delta > 0 else "falling"
    return f"{direction} {magnitude}"


def _describe_deviation(group: str, value: float, baseline: float) -> str:
    """Qualitative description of how far a value sits from the known
    baseline operating point, e.g. 'moderately above baseline'.

    This is the primary signal, not the within-window trend: a fast window
    is only ~12-15 minutes, but a real escalation (see the seed incidents'
    own hours-long progressions) unfolds far slower than that — so the
    *local* delta within one short window is often small even at a
    genuinely elevated, near-trip state, while the *absolute* deviation
    from baseline stays large and consistent across independent noise
    realizations of the same fault. Discovered empirically: an earlier
    version of this function that only described the within-window trend
    measurably hurt held-out retrieval precision/recall versus even the
    raw-numbers baseline, because it discarded this more stable signal.
    """
    threshold = _threshold_for(group, baseline)
    deviation = value - baseline
    if abs(deviation) < threshold:
        return "near baseline"
    ratio = abs(deviation) / threshold
    magnitude = "slightly" if ratio < 3 else ("moderately" if ratio < 8 else "sharply")
    direction = "above" if deviation > 0 else "below"
    return f"{magnitude} {direction} baseline"


def window_to_text(records: list[SimulationRecord], window_kind: str) -> str:
    """Deterministic description of a window, for embedding + BM25 indexing.
    Leads with each channel's deviation from the known baseline operating
    point (the stable, reproducible signal — see _describe_deviation),
    followed by its within-window trend (a secondary, faster-changing
    signal) and exact figures for transparency/debugging. This text is
    never shown to an LLM or user directly (only the hand-authored incident
    narrative is), so this phrasing only affects match quality, not
    explanation quality.
    """
    if not records:
        return f"{window_kind} window: no records."
    first, last = records[0], records[-1]
    duration_min = (last.t_hours - first.t_hours) * 60.0
    parts = [
        f"{window_kind} window, {len(records)} records, {duration_min:.1f} min, "
        f"ending t={last.t_hours:.3f}h."
    ]
    for group, name, unit in WINDOW_SUMMARY_FIELDS:
        v0 = _field(first, group, name)
        v1 = _field(last, group, name)
        delta = v1 - v0
        baseline = _baseline_value(group, name)
        deviation_desc = _describe_deviation(group, v1, baseline)
        trend_desc = _describe_change(group, v0, delta)
        parts.append(
            f"{name} {deviation_desc}, {trend_desc} within window "
            f"({v0:.3f}->{v1:.3f}{unit}, baseline {baseline:.3f}, delta {delta:+.3f})"
        )
    return " ".join(parts)


def build_incident_chunks(
    incident: IncidentDefinition, records: list[SimulationRecord]
) -> tuple[list[DocumentChunk], list[WindowChunk]]:
    """One DocumentChunk (narrative) + up to two WindowChunks (fast, and
    slow if available) per incident stage."""
    doc_chunks: list[DocumentChunk] = []
    window_chunks: list[WindowChunk] = []

    for stage in incident.stages:
        chunk_id = f"{incident.incident_id}::{stage.stage}"
        metadata = {
            "incident_id": incident.incident_id,
            "scenario_type": incident.scenario_type,
            "equipment_zone": incident.equipment_zone,
            "cause_category": incident.cause_category,
            "idv_reference": incident.idv_reference,
            "stage": stage.stage,
            "risk_level": stage.risk_level,
            "t_hours": stage.t_hours,
        }
        # Narrative chunks: run through the same static chunker for
        # consistency, even though these are short enough to rarely split.
        narrative_parts = chunk_static_text(
            stage.narrative.strip(), source_type="incident_narrative", source_name=chunk_id, metadata=metadata
        )
        doc_chunks.extend(narrative_parts)

        pair: WindowPair = window_pair_at(records, stage.record_index)
        window_chunks.append(
            WindowChunk(chunk_id=chunk_id, window_kind="fast", text=window_to_text(pair.fast_records, "fast"), metadata=metadata)
        )
        if pair.has_slow_window:
            window_chunks.append(
                WindowChunk(chunk_id=chunk_id, window_kind="slow", text=window_to_text(pair.slow_records, "slow"), metadata=metadata)
            )

    return doc_chunks, window_chunks
