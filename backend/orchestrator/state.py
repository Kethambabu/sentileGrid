"""Typed LangGraph state schema (CLAUDE.md §3: "wired together via the
LangGraph state object — not free-form message passing"). Every agent's
typed output composes into this single state; LangGraph merges each node's
returned dict into it field by field.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..agents.models import ComplianceResult, EmergencyRecommendation, ExplanationResult, RiskAssessment
from ..agents.sensor_agent import SensorAgentOutput
from ..agents.trend_agent import TrendAgentOutput
from ..rag.retriever import RetrievalOutcome
from ..simulation.models import SimulationRecord


class SentinelGridState(BaseModel):
    run_id: str
    records: list[SimulationRecord]
    equipment_zone: str | None = None

    sensor_output: SensorAgentOutput | None = None
    trend_output: TrendAgentOutput | None = None
    retrieval_outcome: RetrievalOutcome | None = None
    risk_assessment: RiskAssessment | None = None
    compliance_result: ComplianceResult | None = None
    explanation: ExplanationResult | None = None
    emergency_recommendation: EmergencyRecommendation | None = None

    errors: list[str] = Field(default_factory=list)
