"""Drives a scenario through the full agent pipeline and holds run state for
the API layer to serve. CLAUDE.md §3: the frontend only ever talks to this
through backend/api's HTTP/WebSocket surface, never directly to the
database or orchestrator.

Design choice: the physics simulation (Phase 1, no LLM calls, fast) runs to
completion up front; a background thread then "replays" its records at a
configurable pace to simulate live arrival, invoking the full LLM-backed
agent graph only every `assessment_interval_records` records — not on every
single one. Three real LLM calls per assessment make per-record invocation
both too slow for a responsive demo and a good way to blow through free-tier
rate limits (CLAUDE.md §14's documented demo-burst risk), so throttling
assessment cadence is the mitigation, not a shortcut.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..agents.compliance_agent import ComplianceAgent
from ..agents.compound_risk_agent import CompoundRiskAgent
from ..agents.emergency_agent import EmergencyAgent
from ..agents.explanation_agent import ExplanationAgent
from ..agents.retrieval_agent import RetrievalAgent
from ..agents.sensor_agent import SensorAgent
from ..agents.trend_agent import TrendAgent
from ..database.approvals import ApprovalService
from ..database.audit import AuditEntryInput, AuditWriteQueue, get_default_audit_queue
from ..utils.monitoring import log_event
from ..orchestrator.graph import build_graph
from ..orchestrator.state import SentinelGridState
from ..rag.retriever import LiveRetriever
from ..rag.windowing import FAST_WINDOW_SIZE
from ..simulation.models import SimulationRunConfig
from ..simulation.scenario_definitions.base import ScenarioConfig
from ..simulation.simulator import TEPSimulator
from ..utils.llm_router import LLMRouter

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "backend" / "simulation" / "scenario_definitions"

DEFAULT_TICK_SECONDS = 0.2
DEFAULT_ASSESSMENT_INTERVAL_RECORDS = 5


def load_scenario(name: str) -> ScenarioConfig:
    path = SCENARIO_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No scenario definition at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return ScenarioConfig(**yaml.safe_load(f))


def list_scenarios() -> list[ScenarioConfig]:
    return [load_scenario(p.stem) for p in sorted(SCENARIO_DIR.glob("*.yaml"))]


@dataclass
class RunState:
    run_id: str
    scenario_name: str
    status: str = "starting"  # starting | running | completed | error
    total_records: int = 0
    revealed_count: int = 0
    diverged: bool = False
    diverged_reason: str | None = None
    error: str | None = None
    assessments: list[dict] = field(default_factory=list)
    latest_record_summary: dict | None = None
    record_history: list[dict] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self.lock:
            latest_assessment = self.assessments[-1] if self.assessments else None
            return {
                "run_id": self.run_id,
                "scenario_name": self.scenario_name,
                "status": self.status,
                "total_records": self.total_records,
                "revealed_count": self.revealed_count,
                "diverged": self.diverged,
                "diverged_reason": self.diverged_reason,
                "error": self.error,
                "latest_record_summary": self.latest_record_summary,
                "latest_assessment": latest_assessment,
                "assessment_count": len(self.assessments),
            }


class RunManager:
    def __init__(
        self,
        audit_queue: AuditWriteQueue | None = None,
        approval_service: ApprovalService | None = None,
        llm_router: LLMRouter | None = None,
        graph=None,
        retriever: LiveRetriever | None = None,
    ) -> None:
        """All dependencies are overridable — tests build a RunManager with
        a fake LLMRouter (see tests/fakes.py) so exercising the API surface
        never requires live Hugging Face/Groq calls or a network."""
        self.audit_queue = audit_queue or get_default_audit_queue()
        self.approval_service = approval_service or ApprovalService(audit_queue=self.audit_queue)
        self.llm_router = llm_router or LLMRouter(on_response=self._on_llm_response)

        retriever = retriever or LiveRetriever()
        # ComplianceAgent must share the exact same ChromaDB client instance
        # as RetrievalAgent's retriever, not construct its own default one —
        # two separate PersistentClient objects pointed at the same on-disk
        # path both silently diverge from whatever store a caller actually
        # meant (e.g. a test's isolated temp store) and can contend on the
        # underlying SQLite metadata store.
        self.graph = graph or build_graph(
            sensor_agent=SensorAgent(),
            trend_agent=TrendAgent(),
            retrieval_agent=RetrievalAgent(retriever=retriever),
            compound_risk_agent=CompoundRiskAgent(router=self.llm_router),
            compliance_agent=ComplianceAgent(router=self.llm_router, client=retriever.client),
            explanation_agent=ExplanationAgent(router=self.llm_router),
            emergency_agent=EmergencyAgent(router=self.llm_router, approval_service=self.approval_service),
            audit_queue=self.audit_queue,
        )
        self.runs: dict[str, RunState] = {}

    def _on_llm_response(self, request, response) -> None:
        self.audit_queue.submit(
            AuditEntryInput(
                event_type="llm_call",
                payload={"tier_used": response.tier_used.value, "model_name": response.model_name, "latency_ms": response.latency_ms, "cached": response.cached},
            )
        )

    def active_llm_tier(self) -> str | None:
        return self.llm_router.active_tier.value if self.llm_router.active_tier else None

    def start_run(
        self, scenario_name: str, duration_hours: float | None = None,
        tick_seconds: float = DEFAULT_TICK_SECONDS, assessment_interval_records: int = DEFAULT_ASSESSMENT_INTERVAL_RECORDS,
    ) -> str:
        # Validate synchronously, before spawning the worker thread or
        # returning a run_id — otherwise an unknown scenario name gets a
        # 200 response and only fails invisibly in the background.
        scenario = load_scenario(scenario_name)

        run_id = str(uuid.uuid4())
        state = RunState(run_id=run_id, scenario_name=scenario_name)
        self.runs[run_id] = state
        thread = threading.Thread(
            target=self._run_worker, args=(run_id, scenario, duration_hours, tick_seconds, assessment_interval_records), daemon=True
        )
        thread.start()
        return run_id

    def get_run(self, run_id: str) -> RunState | None:
        return self.runs.get(run_id)

    def _run_worker(self, run_id: str, scenario, duration_hours: float | None, tick_seconds: float, assessment_interval_records: int) -> None:
        state = self.runs[run_id]
        log_event("run_started", run_id=run_id, scenario_name=scenario.name)
        try:
            config = SimulationRunConfig(
                scenario_name=scenario.name, duration_hours=duration_hours or scenario.duration_hours,
                idv_schedule=scenario.idv_schedule, noise_enabled=scenario.noise_enabled, random_seed=scenario.random_seed,
            )
            result = TEPSimulator(config).run()
            with state.lock:
                state.diverged = result.diverged
                state.diverged_reason = result.diverged_reason
                state.total_records = len(result.records)
                state.status = "running"
            if result.diverged:
                log_event("run_diverged", run_id=run_id, reason=result.diverged_reason)

            revealed: list = []
            for i, record in enumerate(result.records):
                revealed.append(record)
                summary = {
                    "record_index": i,
                    "t_hours": record.t_hours,
                    "reactor_pressure_kpa": record.xmeas.reactor_pressure_kpa,
                    "reactor_temperature_c": record.xmeas.reactor_temperature_c,
                    "reactor_level_pct": record.xmeas.reactor_level_pct,
                    "separator_pressure_kpa": record.xmeas.separator_pressure_kpa,
                    "stripper_level_pct": record.xmeas.stripper_level_pct,
                }
                with state.lock:
                    state.revealed_count = i + 1
                    state.latest_record_summary = summary
                    state.record_history.append(summary)

                should_assess = (i + 1) >= FAST_WINDOW_SIZE and (i + 1) % assessment_interval_records == 0
                if should_assess:
                    self._run_assessment(run_id, list(revealed))

                time.sleep(tick_seconds)

            with state.lock:
                state.status = "completed"
            log_event("run_completed", run_id=run_id, total_records=state.total_records, assessment_count=len(state.assessments))
        except Exception as exc:  # noqa: BLE001
            with state.lock:
                state.status = "error"
                state.error = str(exc)
            log_event("run_error", run_id=run_id, error=str(exc))

    def _run_assessment(self, run_id: str, records: list) -> None:
        state = self.runs[run_id]
        start = time.monotonic()
        graph_state = SentinelGridState(run_id=run_id, records=records)
        result = self.graph.invoke(graph_state)
        wall_time_ms = (time.monotonic() - start) * 1000.0

        risk = result["risk_assessment"]
        compliance = result["compliance_result"]
        explanation = result["explanation"]
        emergency = result["emergency_recommendation"]
        retrieval = result["retrieval_outcome"]

        log_event(
            "assessment_completed", run_id=run_id, record_index=len(records) - 1, wall_time_ms=wall_time_ms,
            risk_score=risk.risk_score, is_novel_condition=retrieval.is_novel_condition,
            compound_risk_latency_ms=risk.latency_ms, compliance_latency_ms=compliance.latency_ms,
            explanation_latency_ms=explanation.latency_ms, emergency_triggered=emergency.triggered,
        )

        entry = {
            "record_index": len(records) - 1,
            "t_hours": records[-1].t_hours,
            "retrieval_phase": retrieval.phase.value,
            "retrieval_confidence": retrieval.confidence.value,
            "is_novel_condition": retrieval.is_novel_condition,
            "risk_assessment": risk.model_dump(),
            "compliance_result": compliance.model_dump(),
            "explanation": explanation.model_dump(),
            "emergency_recommendation": emergency.model_dump(),
        }
        with state.lock:
            state.assessments.append(entry)
