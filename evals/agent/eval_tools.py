# Owner: Ali
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.repositories.conversation_repo import (  # noqa: E402
    ConversationRecord,
    InMemoryConversationRepository,
)
from app.repositories.embedding_repo import (  # noqa: E402
    EmbeddingChunk,
    InMemoryEmbeddingRepository,
)
from app.repositories.lead_repo import InMemoryLeadRepository  # noqa: E402
from app.services.agent_service import AgentService, ToolPlan, ToolRegistry  # noqa: E402
from app.services.escalation_service import EscalationService  # noqa: E402
from app.services.lead_service import LeadService  # noqa: E402
from app.services.rag_service import RagService  # noqa: E402
from app.services.router_service import RouterService  # noqa: E402


@dataclass(frozen=True)
class ToolEvalCase:
    name: str
    message: str
    expected_decision: str
    expected_agent_tools: tuple[str, ...] = ()
    classifier_label: str = "unknown"
    classifier_confidence: float = 0.4
    contact_email: str | None = None


@dataclass(frozen=True)
class ToolEvalResult:
    total: int
    passed: int
    accuracy: float
    failures: list[str]


class FixedClassifier:
    def __init__(self, *, label: str, confidence: float) -> None:
        self.label = label
        self.confidence = confidence

    def classify(self, message: str) -> tuple[str, float]:
        return self.label, self.confidence


class SequencePlanner:
    def __init__(self, plans: list[ToolPlan]) -> None:
        self.plans = plans

    def plan(self, *, request, tool_calls):
        if len(tool_calls) >= len(self.plans):
            return ToolPlan(None, "eval complete", final_response="Done")
        return self.plans[len(tool_calls)]


DEFAULT_CASES = [
    ToolEvalCase(
        name="faq_routes_to_rag",
        message="What does the team plan cost?",
        expected_decision="rag",
        classifier_label="faq",
        classifier_confidence=0.92,
    ),
    ToolEvalCase(
        name="sales_without_contact_asks_for_contact",
        message="I want a demo",
        expected_decision="capture_lead",
        classifier_label="sales",
        classifier_confidence=0.91,
    ),
    ToolEvalCase(
        name="sales_with_contact_captures_lead",
        message="I want a demo",
        expected_decision="capture_lead",
        classifier_label="sales",
        classifier_confidence=0.91,
        contact_email="buyer@example.com",
    ),
    ToolEvalCase(
        name="human_request_escalates",
        message="I need to talk to a person",
        expected_decision="escalate",
        classifier_label="human_handoff",
        classifier_confidence=0.93,
    ),
    ToolEvalCase(
        name="spam_drops",
        message="free money crypto pump",
        expected_decision="drop",
        classifier_label="spam",
        classifier_confidence=0.98,
    ),
    ToolEvalCase(
        name="ambiguous_multi_step_uses_agent_tools",
        message="Tell me pricing and have someone follow up",
        expected_decision="agent",
        expected_agent_tools=("rag_search", "capture_lead"),
        classifier_label="unknown",
        classifier_confidence=0.42,
        contact_email="buyer@example.com",
    ),
]


def build_rag_service() -> RagService:
    repo = InMemoryEmbeddingRepository(
        [
            EmbeddingChunk(
                chunk_id="tenant-a-pricing",
                tenant_id="tenant-a",
                cms_content_id="cms-tenant-a-pricing",
                title="Pricing",
                text="The team plan costs 49 dollars per month and includes onboarding.",
                url="https://tenant-a.example/pricing",
            )
        ]
    )
    return RagService(repo)


def build_escalation_service() -> EscalationService:
    # Mocked Mohammad-owned persistence input:
    # this conversation row should eventually come from the tenant-scoped DB/RLS layer.
    repo = InMemoryConversationRepository(
        [
            ConversationRecord(
                tenant_id="tenant-a",
                conversation_id="conversation-a",
                visitor_session_id="visitor-a",
            )
        ]
    )
    return EscalationService(repo)


def build_router(case: ToolEvalCase) -> RouterService:
    # Mocked Jana-owned classifier input:
    # labels/confidence should eventually come from modelserver via classifier_client.py.
    return RouterService(
        classifier=FixedClassifier(
            label=case.classifier_label,
            confidence=case.classifier_confidence,
        ),
        rag_tool=build_rag_service(),
        lead_tool=LeadService(InMemoryLeadRepository()),
        escalation_tool=build_escalation_service(),
    )


def build_agent() -> AgentService:
    # Mocked LLM planner:
    # replace this deterministic sequence with the real tool-calling LLM once prompts,
    # guardrails, and hosted model configuration are available.
    planner = SequencePlanner(
        [
            ToolPlan("rag_search", "answer tenant question"),
            ToolPlan("capture_lead", "capture follow-up details"),
        ]
    )
    return AgentService(
        tool_registry=ToolRegistry(
            rag_tool=build_rag_service(),
            lead_tool=LeadService(InMemoryLeadRepository()),
            escalation_tool=build_escalation_service(),
        ),
        planner=planner,
    )


def request_payload(case: ToolEvalCase) -> dict:
    return {
        "tenant_id": "tenant-a",
        "conversation_id": "conversation-a",
        "visitor_session_id": "visitor-a",
        "message": case.message,
        # Mocked Charbel-owned widget input:
        # source_url/contact fields should eventually come from the authenticated widget payload.
        "source_url": "https://tenant-a.example/pricing",
        "contact_email": case.contact_email,
        "trace_id": f"eval-{case.name}",
    }


def run_eval(cases: list[ToolEvalCase]) -> ToolEvalResult:
    failures: list[str] = []
    for case in cases:
        router_result = build_router(case).route(request_payload(case))
        if router_result.decision != case.expected_decision:
            failures.append(
                f"{case.name}: expected {case.expected_decision}, got {router_result.decision}"
            )
            continue
        if case.expected_agent_tools:
            agent_result = build_agent().run(request_payload(case))
            actual_tools = tuple(call.tool_name for call in agent_result.tool_calls)
            if actual_tools != case.expected_agent_tools:
                failures.append(
                    f"{case.name}: expected tools {case.expected_agent_tools}, got {actual_tools}"
                )
    total = len(cases)
    passed = total - len(failures)
    return ToolEvalResult(
        total=total,
        passed=passed,
        accuracy=passed / total if total else 0.0,
        failures=failures,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run router/agent tool-selection evals.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()

    result = run_eval(DEFAULT_CASES)
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print(f"Tool-selection accuracy: {result.accuracy:.2f} ({result.passed}/{result.total})")
        if result.failures:
            print("Failures:")
            for failure in result.failures:
                print(f"- {failure}")
    return 0 if not result.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
