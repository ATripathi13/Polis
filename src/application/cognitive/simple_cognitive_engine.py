"""
Default implementation of the Polis Cognitive Engine.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from application.cognitive.cognitive_engine import (
    CognitiveEngine,
)

from application.cognitive.cognitive_planner import (
    CognitivePlanner,
)

from application.cognitive.multi_step_coordinator import (
    MultiStepCoordinator,
    StepExecutor,
)

from application.pipeline.pipeline import (
    PolisPipeline,
)

from domain.calendar.exceptions import (
    CalendarDomainError,
    CalendarEntryNotFoundError,
    InvalidAudienceError,
    InvalidCalendarEntryError,
    InvalidTimeRangeError,
    UnauthorizedCalendarActionError,
)

from domain.common.identifier import Identifier

from domain.governance.enums import ApprovalStatus
from domain.governance.exceptions import (
    ApprovalNotFoundError,
    GovernanceError,
    InvalidApprovalTransitionError,
    PolicyNotFoundError,
)

from domain.observation import (
    Observation,
    ObservationType,
)

from domain.operations import (
    InvalidLifecycleTransitionError,
    OperationalError,
    OperationalItem,
    OperationalItemNotFoundError,
    OperationalItemPriority,
    OperationalItemRepository,
    OperationalItemStatus,
    OperationalItemType,
    UnsupportedOperationalEventError,
)

from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)

from domain.reasoning import (
    Question,
    Answer,
    QuestionAnsweringService,
)

from domain.reasoning.value_objects.request_plan import (
    ActionType,
    CognitivePlan,
    ExecutionStep,
    IntentCategory,
    PendingOperation,
    TargetAgent,
)

from domain.reasoning.value_objects.step_execution import (
    MultiStepExecutionResult,
    MultiStepExecutionStatus,
    StepExecutionResult,
    StepExecutionStatus,
)

logger = logging.getLogger(__name__)


class SimpleCognitiveEngine(
    CognitiveEngine,
):
    """
    Default implementation of the
    Polis Cognitive Engine.
    """

    def __init__(
        self,
        pipeline: PolisPipeline,
        question_answering: QuestionAnsweringService,
        activity_question_service=None,
        operational_item_service=None,
        knowledge_base_retrieval_service=None,
        knowledge_base_answer_service=None,
        knowledge_agent=None,
        operations_agent=None,
        governance_agent=None,
        meeting_intelligence_service=None,
        calendar_agent=None,
        planner: CognitivePlanner | None = None,
        coordinator: MultiStepCoordinator | None = None,
        operational_item_repository: OperationalItemRepository | None = None,
        identity_resolver: Any | None = None,
        person_work_service: Any | None = None,
    ) -> None:

        self._pipeline = pipeline

        self._question_answering = (
            question_answering
        )

        self._activity_question_service = (
            activity_question_service
        )

        self._operational_item_service = (
            operational_item_service
        )

        self._knowledge_base_retrieval_service = (
            knowledge_base_retrieval_service
        )

        self._knowledge_base_answer_service = (
            knowledge_base_answer_service
        )

        self._knowledge_agent = knowledge_agent
        self._operations_agent = operations_agent
        self._governance_agent = governance_agent
        self._meeting_intelligence_service = (
            meeting_intelligence_service
        )
        self._calendar_agent = calendar_agent
        self._operational_item_repository = operational_item_repository
        self._identity_resolver = identity_resolver
        self._person_work_service = person_work_service

        if planner is not None:
            self._planner = planner
        else:
            llm_client = getattr(question_answering, "_llm_client", None)
            self._planner = CognitivePlanner(llm_client=llm_client)

        if coordinator is not None:
            self._coordinator = coordinator
        else:
            self._coordinator = MultiStepCoordinator()

    @property
    def planner(self) -> CognitivePlanner:
        return self._planner

    @property
    def coordinator(self) -> MultiStepCoordinator:
        return self._coordinator

    @property
    def person_work_service(self):
        return self._person_work_service

    @property
    def knowledge_agent(self):
        return self._knowledge_agent

    @property
    def operations_agent(self):
        return self._operations_agent

    @property
    def governance_agent(self):
        return self._governance_agent

    @property
    def calendar_agent(self):
        return self._calendar_agent

    @property
    def meeting_intelligence_service(self):
        return self._meeting_intelligence_service

    def learn(
        self,
        communication,
    ) -> None:
        """
        Learn from a communication.
        """

        self._pipeline.process(
            communication,
        )

    @classmethod
    def _build_specialist_retrieval_question(
        cls,
        agent: TargetAgent,
        question: Question,
    ) -> Question:
        """
        Build a retrieval-only representation of Question for specialist evidence retrieval,
        resolving anaphoric references using relevant recent conversation history without mutating
        the original Question or leaking cross-domain antecedents.
        """
        context = question.context
        if context is None or not context.history:
            return question

        raw_text = (question.text or "").strip()
        lowered = raw_text.lower()

        # Check for explicit topic shift / reset cues (do not drag previous topic's antecedents)
        topic_shift = bool(
            re.search(
                r"^\s*(?:now\s+let'?s\s+(?:discuss|talk\s+about|move\s+to)|on\s+another\s+note|changing\s+topics?|switch\s+topics?|unrelated|different\s+question|by\s+the\s+way)\b",
                lowered,
            )
        )
        if topic_shift:
            return question

        # Check for anaphoric / follow-up cues
        anaphora_pattern = re.compile(
            r"\b(it|this|that|these|those|them|its|"
            r"the\s+(?:meeting|event|activity|holiday|announcement|task|decision|risk|policy|violation|approval|finding|project|database|doc|document|code|campaign|system))\b",
            re.IGNORECASE,
        )
        followup_cues = re.compile(
            r"\b(?:who\s+is\s+(?:attending|invited|assigned|the\s+owner|responsible)|"
            r"who\s+owns|who\s+requested|who\s+asked|what\s+time|when\s+is\s+it|where\s+is\s+it|"
            r"is\s+it\s+(?:open|done|closed|active|overdue|approved|rejected|compliant|confirmed)|"
            r"are\s+any\s+(?:of\s+them\s+|of\s+those\s+)?overdue|"
            r"what\s+is\s+the\s+status|what\s+is\s+the\s+priority|what\s+is\s+the\s+severity|"
            r"tell\s+me\s+more|which\s+(?:one|ones|databases?|platforms?|campaigns?|policies?)|"
            r"how\s+does\s+that\s+work)\b",
            re.IGNORECASE,
        )

        is_anaphoric = bool(anaphora_pattern.search(lowered) or followup_cues.search(lowered))
        if not is_anaphoric and len(raw_text.split()) > 6:
            # Query is sufficiently standalone with no anaphora
            return question

        # Inspect recent history messages (last 4 messages / 2 turns)
        recent_messages = context.history[-4:]
        antecedent_tokens: list[str] = []

        if agent == TargetAgent.CALENDAR_AGENT:
            cal_title_match = None
            # 1. Prioritize grounded assistant evidence first
            for msg in reversed(recent_messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    m_grounded = re.findall(
                        r"Calendar Entry\s*\[[^\]]+\]:\s*['\"]([^'\"]+)['\"]",
                        content,
                        re.IGNORECASE,
                    )
                    if len(m_grounded) > 1:
                        return question
                    if len(m_grounded) == 1:
                        cal_title_match = m_grounded[0]
                        break

            # 2. If no grounded assistant evidence, check general messages
            if not cal_title_match:
                for msg in reversed(recent_messages):
                    content = msg.get("content", "")
                    m = re.findall(r"(?:event\s+['\"]([^'\"]+)['\"]|meeting\s+['\"]([^'\"]+)['\"])", content, re.IGNORECASE)
                    flat_m = [item[0] or item[1] for item in m if (item[0] or item[1])]
                    if len(flat_m) > 1:
                        return question
                    if len(flat_m) == 1:
                        cal_title_match = flat_m[0]
                        break

            if cal_title_match and cal_title_match.lower() not in lowered:
                antecedent_tokens.append(f"calendar event {cal_title_match}")
            elif any("calendar" in msg.get("content", "").lower() or "meeting" in msg.get("content", "").lower() for msg in recent_messages):
                antecedent_tokens.append("calendar meeting event")

        elif agent == TargetAgent.OPERATIONS_AGENT:
            has_task = False
            has_risk = False
            has_decision = False
            task_summary = None

            # 1. Prioritize grounded assistant evidence first
            for msg in reversed(recent_messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    m_all = re.findall(
                        r"Operational item:\s*task.*?Summary:\s*([^\n\r]+)",
                        content,
                        re.IGNORECASE | re.DOTALL,
                    )
                    if len(m_all) > 1:
                        return question
                    if len(m_all) == 1:
                        task_summary = m_all[0].strip()
                        has_task = True
                        break  # Stop at newest valid grounded task!

            # 2. If no grounded assistant evidence found, check newest valid task antecedent
            if not task_summary:
                for msg in reversed(recent_messages):
                    content = msg.get("content", "")
                    m_t = re.findall(r"(?:Operational item:\s*task.*?Summary:\s*([^\n\r]+)|task\s+['\"]([^'\"]+)['\"])", content, re.IGNORECASE | re.DOTALL)
                    flat_m_t = [t[0] or t[1] for t in m_t if (t[0] or t[1])]
                    if len(flat_m_t) > 1:
                        return question
                    if len(flat_m_t) == 1:
                        task_summary = flat_m_t[0].strip()
                        has_task = True
                        break  # Stop at newest!
                    lower_c = content.lower()
                    if "task" in lower_c:
                        has_task = True
                        break
                    if "risk" in lower_c or "blocker" in lower_c:
                        has_risk = True
                        break
                    if "decision" in lower_c or "decided" in lower_c:
                        has_decision = True
                        break

            if has_task and "task" not in lowered:
                antecedent_tokens.append("task")
            if task_summary and task_summary.lower() not in lowered:
                antecedent_tokens.append(task_summary)
            if has_risk and "risk" not in lowered and not has_task:
                antecedent_tokens.append("risk")
            if has_decision and "decision" not in lowered and not has_task and not has_risk:
                antecedent_tokens.append("decision")

        elif agent == TargetAgent.GOVERNANCE_AGENT:
            policy_id = None
            approval_name = None

            # 1. Prioritize grounded assistant evidence first
            for msg in reversed(recent_messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    grounded_pols = re.findall(r"(?:Governance Finding|Policy)\s*\[([A-Z]{2,6}-\d{2,4})\]", content)
                    if len(set(grounded_pols)) > 1:
                        return question
                    if len(set(grounded_pols)) == 1:
                        policy_id = grounded_pols[0]
                        break

                    apps = re.findall(r"(?:Pending Approval:\s*['\"]([^'\"]+)['\"]|Approval Request:\s*['\"]([^'\"]+)['\"])", content, re.IGNORECASE)
                    flat_apps = [a[0] or a[1] for a in apps if (a[0] or a[1])]
                    if len(flat_apps) > 1:
                        return question
                    if len(flat_apps) == 1:
                        approval_name = flat_apps[0].strip()
                        break

            # 2. If no grounded assistant evidence, check general messages
            if not policy_id and not approval_name:
                for msg in reversed(recent_messages):
                    content = msg.get("content", "")
                    pols = re.findall(r"\b([A-Z]{2,6}-\d{2,4})\b", content)
                    if len(set(pols)) > 1:
                        return question
                    if len(set(pols)) == 1:
                        policy_id = pols[0]
                        break

            if policy_id and policy_id.lower() not in lowered:
                antecedent_tokens.append(f"policy {policy_id}")
            elif approval_name and approval_name.lower() not in lowered:
                antecedent_tokens.append(f"approval {approval_name}")
            elif any("compliance" in msg.get("content", "").lower() or "violation" in msg.get("content", "").lower() for msg in recent_messages):
                antecedent_tokens.append("compliance policy violation")

        elif agent == TargetAgent.KNOWLEDGE_AGENT:
            substantive_topics = []
            for msg in reversed(recent_messages):
                content = msg.get("content", "")
                matches = re.findall(
                    r"\b([A-Z][a-zA-Z0-9_+.-]+(?:\s+[A-Z0-9][a-zA-Z0-9_+.-]+)*|\b(?:postgres(?:ql)?|qdrant|minio|redis|auth|oauth|vpn|zero\s+trust)\b)\b",
                    content,
                    re.IGNORECASE,
                )
                for match in matches:
                    cand = match.strip()
                    if cand and len(cand) > 2 and cand.lower() not in ("user", "polis", "assistant", "today", "tomorrow"):
                        if cand.lower() not in [s.lower() for s in substantive_topics]:
                            substantive_topics.append(cand)
                if substantive_topics:
                    break

            for topic in substantive_topics[:2]:
                if topic.lower() not in lowered:
                    antecedent_tokens.append(topic)

        if not antecedent_tokens:
            return question

        resolved_retrieval_text = f"{raw_text} {' '.join(antecedent_tokens)}"
        return Question(
            text=resolved_retrieval_text,
            context=question.context,
            target_user_id=question.target_user_id,
            target_user_name=question.target_user_name,
        )

    def ask(
        self,
        question: Question,
    ) -> Answer:
        """
        Answer a question with cognitive planning and selective specialist orchestration.

        Orchestration flow:
        1. Deterministic activity fast-path.
        2. Plan creation or pending-operation continuation.
        3. Cancellation / Clarification / Action execution.
        4. Selective specialist evidence collection.
        5. Grounded synthesis and pending state management.
        """

        # ------------------------------------------------------
        # 1. ACTIVITY QUESTIONS (Fast deterministic path)
        # ------------------------------------------------------
        if self._activity_question_service is not None:
            activity_answer = (
                self._activity_question_service.answer(
                    question,
                )
            )
            if activity_answer is not None:
                return activity_answer

        # ------------------------------------------------------
        # 2. COGNITIVE PLANNING & CONTEXT EVALUATION
        # ------------------------------------------------------
        context = question.context
        plan: CognitivePlan = self._planner.plan(question, context=context)

        # ------------------------------------------------------
        # 3. CANCEL ACTION
        # ------------------------------------------------------
        if plan.intent == IntentCategory.CANCEL_ACTION and not plan.requires_clarification:
            active_op = (
                context.get_typed_pending_operation(
                    expected_user_id=context.user_id,
                    expected_channel_id=context.channel_id,
                    expected_thread_ts=getattr(context, "expected_thread_ts", None),
                )
                if context and context.user_id
                else None
            )
            if active_op and active_op.is_multi_step and active_op.completed_step_results:
                completed_count = len(active_op.completed_step_results)
                completed_summaries = []
                for sid, res_data in active_op.completed_step_results.items():
                    act = res_data.get("action", "step")
                    eid = res_data.get("entity_id") or res_data.get("output_fields", {}).get("entity_id", "")
                    if eid:
                        completed_summaries.append(f"• Step '{sid}' ({act}): Completed (ID: `{eid}`).")
                    else:
                        completed_summaries.append(f"• Step '{sid}' ({act}): Completed.")

                msg = (
                    f"I've cancelled the remaining operations for plan `{active_op.plan_id}`.\n\n"
                    f"ℹ️ Note: {completed_count} prior step(s) were already executed and have not been undone:\n"
                    + "\n".join(completed_summaries)
                )
                return Answer(
                    text=msg,
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=True,
                )

            return Answer(
                text="I've cancelled that operation for you.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=True,
            )

        # ------------------------------------------------------
        # 4. MISSING INFORMATION & CLARIFICATION
        # ------------------------------------------------------
        if plan.requires_clarification:
            # 1. Stateless API request (no conversation context)
            if context is None:
                return Answer(
                    text=plan.clarification_prompt or "Could you please clarify your request?",
                    confidence=1.0,
                    is_conversational=True,
                    pending_operation=None,
                )

            # 2. Purely conversational clarification (e.g. ambiguous informational query)
            is_action_clarification = (
                plan.action_required
                or len(plan.execution_steps) > 0
                or plan.intent in (
                    IntentCategory.TASK_ACTION,
                    IntentCategory.CALENDAR_ACTION,
                    IntentCategory.REMINDER_ACTION,
                    IntentCategory.GOVERNANCE_ACTION,
                    IntentCategory.CANCEL_ACTION,
                )
            )

            if not is_action_clarification:
                # Purely conversational clarification (e.g. ambiguous informational query)
                return Answer(
                    text=plan.clarification_prompt or "Could you please clarify your request?",
                    confidence=1.0,
                    is_conversational=True,
                    pending_operation=None,
                )

            # 3. Action clarification in conversational context requires valid scope
            if not context.user_id or not context.channel_id:
                logger.warning(
                    "Cannot establish pending operation for clarification: missing user or channel context (engine=%s, operation=%s)",
                    "simple_cognitive_engine",
                    "clarification_scope",
                )
                return Answer(
                    text="I need additional context (channel and user identification) to process this request.",
                    confidence=0.5,
                    is_conversational=True,
                    pending_operation=None,
                )

            req_user = context.user_id
            channel_id = context.channel_id
            raw_thread = str(context.thread_ts or "").strip()

            is_dm = (
                getattr(context, "channel_type", None) == "im"
                or (isinstance(channel_id, str) and channel_id.startswith("D"))
            )
            is_unthreaded_dm = is_dm and not getattr(context, "is_thread", False)

            # Scope validation: Threaded contexts and non-DM channels MUST have a valid thread_ts.
            # Unthreaded DMs are scoped by user_id and channel_id per Logical Change 3.
            has_sufficient_scope = bool(raw_thread or is_unthreaded_dm)
            if not has_sufficient_scope:
                logger.warning(
                    "Cannot establish pending operation for clarification: insufficient context scope (engine=%s, operation=%s)",
                    "simple_cognitive_engine",
                    "clarification_scope",
                )
                return Answer(
                    text="I need additional context (channel and user identification) to process this request.",
                    confidence=0.5,
                    is_conversational=True,
                    pending_operation=None,
                )

            active_op = context.get_typed_pending_operation(
                expected_user_id=req_user,
                expected_channel_id=channel_id,
                expected_thread_ts=getattr(context, "expected_thread_ts", None),
            )
            op_id = active_op.operation_id if active_op else f"op_{uuid.uuid4().hex[:12]}"
            target_ag = plan.required_agents[0] if plan.required_agents else TargetAgent.GENERAL_REASONER
            action_name = plan.execution_steps[0].action if plan.execution_steps else ""
            collected = plan.entities.model_dump(exclude_unset=True)
            if active_op:
                collected = {**active_op.collected_entities, **collected}

            now_dt = datetime.now(timezone.utc)
            expires_dt = now_dt + timedelta(minutes=15)

            is_multi = bool(active_op and active_op.is_multi_step) or len(plan.execution_steps) > 1
            plan_id_val = active_op.plan_id if (active_op and active_op.plan_id) else (plan.request_id if is_multi else None)
            orig_plan_dict = active_op.original_plan if (active_op and active_op.original_plan) else (plan.model_dump() if is_multi else None)
            completed_results = active_op.completed_step_results if active_op else {}
            step_states_dict = active_op.step_states if active_op else {}
            pending_step = active_op.pending_step_id if (active_op and active_op.pending_step_id) else (plan.execution_steps[0].step_id if plan.execution_steps else None)

            try:
                new_pending = PendingOperation(
                    operation_id=op_id,
                    intent=plan.intent,
                    target_agent=target_ag,
                    action=action_name,
                    collected_entities=collected,
                    missing_fields=plan.missing_information,
                    clarification_question=plan.clarification_prompt or "",
                    user_id=req_user,
                    channel_id=channel_id,
                    thread_ts=raw_thread,
                    created_at_iso=now_dt.isoformat(),
                    expires_at_iso=expires_dt.isoformat(),
                    state_version=1,
                    plan_id=plan_id_val,
                    original_plan=orig_plan_dict,
                    step_states=step_states_dict,
                    completed_step_results=completed_results,
                    pending_step_id=pending_step,
                )
                pending_dict = new_pending.model_dump()
            except Exception:
                logger.error(
                    "Failed to construct pending operation (engine=%s, operation=%s)",
                    "simple_cognitive_engine",
                    "create_pending_operation",
                )
                return Answer(
                    text="An error occurred while preparing this request for clarification. Please try again.",
                    confidence=0.0,
                    is_conversational=True,
                    pending_operation=None,
                )

            return Answer(
                text=plan.clarification_prompt or "Could you please clarify your request?",
                confidence=1.0,
                is_conversational=True,
                pending_operation=pending_dict,
            )

        is_action_plan = (
            plan.action_required
            or plan.intent in (
                IntentCategory.TASK_ACTION,
                IntentCategory.CALENDAR_ACTION,
                IntentCategory.REMINDER_ACTION,
                IntentCategory.GOVERNANCE_ACTION,
            )
            or any(
                step.action_type in (ActionType.CREATE, ActionType.UPDATE, ActionType.CANCEL)
                for step in plan.execution_steps
            )
        )
        if is_action_plan:
            # Multi-step plan execution (MultiStepCoordinator)
            if len(plan.execution_steps) > 1:
                return self._dispatch_multi_step_plan(plan, question, context)

            # Calendar action execution (CalendarAgent)
            if (
                plan.intent == IntentCategory.CALENDAR_ACTION
                or any(
                    step.agent == TargetAgent.CALENDAR_AGENT
                    and step.action_type in (ActionType.CREATE, ActionType.UPDATE, ActionType.CANCEL)
                    for step in plan.execution_steps
                )
            ):
                return self._dispatch_calendar_action(plan, question, context)

            # Reminder action execution (OperationsAgent / ReminderService)
            if (
                plan.intent == IntentCategory.REMINDER_ACTION
                or any(
                    step.agent == TargetAgent.REMINDER_SERVICE
                    or (step.agent == TargetAgent.OPERATIONS_AGENT and "reminder" in step.action.lower())
                    for step in plan.execution_steps
                )
            ):
                return self._dispatch_reminder_action(plan, question, context)

            # Governance action execution (GovernanceAgent)
            if (
                plan.intent == IntentCategory.GOVERNANCE_ACTION
                or any(
                    step.agent == TargetAgent.GOVERNANCE_AGENT
                    and step.action_type in (ActionType.CREATE, ActionType.UPDATE)
                    for step in plan.execution_steps
                )
            ):
                return self._dispatch_governance_action(plan, question, context)

            # Task action execution (OperationsAgent)
            if (
                plan.intent == IntentCategory.TASK_ACTION
                or any(
                    step.agent == TargetAgent.OPERATIONS_AGENT
                    and step.action_type in (ActionType.CREATE, ActionType.UPDATE)
                    for step in plan.execution_steps
                )
            ):
                return self._dispatch_task_action(plan, question, context)

        # ------------------------------------------------------
        # EMPLOYEE WORK QUERY (Person-Specific Work & Tasks)
        # ------------------------------------------------------
        if plan.intent == IntentCategory.EMPLOYEE_WORK_QUERY:
            return self._handle_employee_work_query(question, context, plan)

        # ------------------------------------------------------
        # 6. GENERAL CONVERSATION FAST PATH
        # ------------------------------------------------------
        if plan.intent == IntentCategory.GENERAL_CONVERSATION:
            if self._is_greeting_message(question):
                briefing_answer = self._handle_morning_briefing(question, context)
                if briefing_answer is not None:
                    return briefing_answer
            return self._question_answering.answer(question)

        # ------------------------------------------------------
        # 7. SELECTIVE SPECIALIST EVIDENCE RETRIEVAL
        # ------------------------------------------------------
        retrieve_evidence = getattr(
            self._question_answering,
            "retrieve_evidence",
            None,
        )

        answer_from_evidence = getattr(
            self._question_answering,
            "answer_from_evidence",
            None,
        )

        if (
            callable(retrieve_evidence)
            and callable(answer_from_evidence)
        ):
            req_agents = plan.required_agents

            organizational_evidence: list[str] = []
            if TargetAgent.GENERAL_REASONER in req_agents or not req_agents:
                organizational_evidence = retrieve_evidence(question)

            operational_evidence: list[str] = []
            if TargetAgent.OPERATIONS_AGENT in req_agents:
                ops_q = self._build_specialist_retrieval_question(TargetAgent.OPERATIONS_AGENT, question)
                if self._operations_agent is not None:
                    operational_evidence = self._operations_agent.retrieve_evidence(ops_q)
                elif self._operational_item_service is not None:
                    operational_evidence = self._operational_item_service.retrieve_evidence(ops_q)

            knowledge_base_evidence: list[str] = []
            if TargetAgent.KNOWLEDGE_AGENT in req_agents or not req_agents:
                kb_q = self._build_specialist_retrieval_question(TargetAgent.KNOWLEDGE_AGENT, question)
                if self._knowledge_agent is not None:
                    knowledge_base_evidence = self._knowledge_agent.retrieve_evidence(kb_q, limit=5)
                elif self._knowledge_base_retrieval_service is not None:
                    knowledge_results = self._knowledge_base_retrieval_service.retrieve(
                        kb_q.text,
                        limit=5,
                        employee_slack_user_id=question.target_user_id,
                    )
                    for chunk, _score in knowledge_results:
                        content = chunk.content.strip()
                        if not content:
                            continue
                        document_name = chunk.metadata.get("document_name", "Unknown")
                        knowledge_base_evidence.append(
                            f"Knowledge Base document: {document_name}\n{content}"
                        )

            governance_evidence: list[str] = []
            if TargetAgent.GOVERNANCE_AGENT in req_agents and self._governance_agent is not None:
                gov_q = self._build_specialist_retrieval_question(TargetAgent.GOVERNANCE_AGENT, question)
                governance_evidence = self._governance_agent.retrieve_evidence(gov_q)

            calendar_evidence: list[str] = []
            if TargetAgent.CALENDAR_AGENT in req_agents and self._calendar_agent is not None:
                cal_q = self._build_specialist_retrieval_question(TargetAgent.CALENDAR_AGENT, question)
                calendar_evidence = self._calendar_agent.retrieve_evidence(cal_q)

            unified_evidence = (
                organizational_evidence
                + operational_evidence
                + knowledge_base_evidence
                + governance_evidence
                + calendar_evidence
            )

            if not unified_evidence:
                if not organizational_evidence:
                    organizational_evidence = retrieve_evidence(question)
                unified_evidence = organizational_evidence

            if unified_evidence:
                grounded = answer_from_evidence(
                    question,
                    unified_evidence,
                    fallback_evidence=organizational_evidence,
                )
                clear = bool(context and context.pending_operation)
                return Answer(
                    text=grounded.text,
                    confidence=grounded.confidence,
                    evidence=grounded.evidence,
                    is_conversational=grounded.is_conversational,
                    clear_pending=clear,
                )

        # ------------------------------------------------------
        # 8. EXISTING REASONING FALLBACK
        # ------------------------------------------------------
        fallback_ans = self._question_answering.answer(
            question,
        )
        clear = bool(context and context.pending_operation)
        return Answer(
            text=fallback_ans.text,
            confidence=fallback_ans.confidence,
            evidence=fallback_ans.evidence,
            is_conversational=fallback_ans.is_conversational,
            clear_pending=clear,
        )


    def ask_knowledge(
        self,
        question: Question | str,
    ):
        """
        Ask the specialist Knowledge Agent directly.
        """
        if self._knowledge_agent is not None:
            return self._knowledge_agent.ask(question)
        return None

    def ask_operations(
        self,
        question: Question | str,
    ):
        """
        Ask the specialist Operations Agent directly.
        """
        if self._operations_agent is not None:
            return self._operations_agent.ask(question)
        return None

    def ask_governance(
        self,
        question: Question | str,
    ):
        """
        Ask the specialist Governance Agent directly.
        """
        if self._governance_agent is not None:
            return self._governance_agent.ask(question)
        return None

    def ask_calendar(
        self,
        question: Question | str,
    ):
        """
        Ask the specialist Calendar Agent directly.
        """
        if self._calendar_agent is not None:
            return self._calendar_agent.ask(question)
        return None

    def summarize_meeting(
        self,
        meeting_id: str,
    ) -> Answer:
        """
        Summarize a meeting via the specialist Meeting Intelligence capability.
        """
        if self._meeting_intelligence_service is not None:
            return self._meeting_intelligence_service.summarize(meeting_id)
        return Answer(
            text="Meeting intelligence service is not configured.",
            confidence=0.0,
            evidence=[],
        )

    def analyze_meeting(
        self,
        meeting_id: str,
    ):
        """
        Produce structured meeting intelligence via the specialist Meeting Intelligence capability.
        """
        if self._meeting_intelligence_service is not None:
            return self._meeting_intelligence_service.analyze(meeting_id)
        raise ValueError("Meeting intelligence service is not configured.")

    # =========================================================================
    # MULTI-STEP COORDINATION & SPECIALIST EXECUTION BRIDGE (Stage B5.3)
    # =========================================================================

    def _dispatch_multi_step_plan(
        self,
        plan: CognitivePlan,
        question: Question,
        context: ConversationContext | None,
    ) -> Answer:
        """
        Execute a multi-step plan using MultiStepCoordinator and specialist execution bridge.
        Supports safe resumption from prior successful step results without repeating completed mutations.
        """
        # 1. Retrieve initial completed results from active pending operation if resuming
        initial_results: dict[str, StepExecutionResult] = {}
        active_op: PendingOperation | None = None
        if context is not None and context.user_id:
            active_op = context.get_typed_pending_operation(
                expected_user_id=context.user_id,
                expected_channel_id=context.channel_id,
                expected_thread_ts=getattr(context, "expected_thread_ts", None),
            )
            if active_op and active_op.is_multi_step:
                initial_results = active_op.get_completed_results()

        multi_result = self._coordinator.execute(
            plan,
            step_executor=lambda step, p, params, prereqs: self._execute_specialist_step(
                step=step,
                plan=p,
                resolved_parameters=params,
                prerequisite_results=prereqs,
                question=question,
                context=context,
            ),
            initial_step_results=initial_results,
        )

        is_success = multi_result.is_all_succeeded
        confidence = 1.0 if is_success else 0.5

        # 2. If execution paused because clarification is required
        if multi_result.status == MultiStepExecutionStatus.CLARIFICATION_REQUIRED:
            if context is None:
                return Answer(
                    text=multi_result.overall_answer,
                    confidence=1.0,
                    is_conversational=True,
                    pending_operation=None,
                    clear_pending=False,
                )

            if not context.user_id or not context.channel_id:
                logger.warning(
                    "Cannot establish pending operation for clarification: missing user or channel context (engine=%s, operation=%s)",
                    "simple_cognitive_engine",
                    "clarification_scope",
                )
                return Answer(
                    text="I need additional context (channel and user identification) to process this request.",
                    confidence=0.5,
                    is_conversational=True,
                    pending_operation=None,
                )

            req_user = context.user_id
            channel_id = context.channel_id
            raw_thread = str(context.thread_ts or "").strip()

            is_dm = (
                getattr(context, "channel_type", None) == "im"
                or (isinstance(channel_id, str) and channel_id.startswith("D"))
            )
            is_unthreaded_dm = is_dm and not getattr(context, "is_thread", False)

            has_sufficient_scope = bool(raw_thread or is_unthreaded_dm)
            if not has_sufficient_scope:
                logger.warning(
                    "Cannot establish pending operation for clarification: insufficient context scope (engine=%s, operation=%s)",
                    "simple_cognitive_engine",
                    "clarification_scope",
                )
                return Answer(
                    text="I need additional context (channel and user identification) to process this request.",
                    confidence=0.5,
                    is_conversational=True,
                    pending_operation=None,
                )

            op_id = active_op.operation_id if active_op else f"op_{uuid.uuid4().hex[:12]}"
            target_ag = plan.required_agents[0] if plan.required_agents else TargetAgent.GENERAL_REASONER
            action_name = plan.execution_steps[0].action if plan.execution_steps else ""

            pending_step_id = None
            clarify_step = None
            for sid, res in multi_result.step_results.items():
                if (
                    res.status == StepExecutionStatus.PENDING
                    or res.output_fields.get("requires_clarification")
                    or res.action == "clarify"
                ):
                    pending_step_id = sid
                    clarify_step = res
                    break

            missing_f = plan.missing_information
            clarify_q = multi_result.overall_answer
            if clarify_step:
                if clarify_step.error and clarify_step.error != "clarification_required":
                    missing_f = [clarify_step.error]
                if clarify_step.answer:
                    clarify_q = clarify_step.answer

            # Serialize successful step results safely excluding domain_result
            completed_results: dict[str, dict[str, Any]] = {}
            step_states: dict[str, str] = {}
            for sid, res in multi_result.step_results.items():
                step_states[sid] = res.status.value
                if res.status == StepExecutionStatus.SUCCEEDED:
                    completed_results[sid] = res.model_dump(exclude={"domain_result"})

            now_dt = datetime.now(timezone.utc)
            expires_dt = now_dt + timedelta(minutes=15)
            try:
                new_pending = PendingOperation(
                    operation_id=op_id,
                    intent=plan.intent,
                    target_agent=target_ag,
                    action=action_name,
                    collected_entities=active_op.collected_entities if active_op else {},
                    missing_fields=missing_f,
                    clarification_question=clarify_q,
                    user_id=req_user,
                    channel_id=channel_id,
                    thread_ts=raw_thread,
                    created_at_iso=now_dt.isoformat(),
                    expires_at_iso=expires_dt.isoformat(),
                    state_version=1,
                    plan_id=plan.request_id,
                    original_plan=plan.model_dump(),
                    step_states=step_states,
                    completed_step_results=completed_results,
                    pending_step_id=pending_step_id,
                )
                pending_dict = new_pending.model_dump()
            except Exception:
                logger.error(
                    "Failed to construct pending operation (engine=%s, operation=%s)",
                    "simple_cognitive_engine",
                    "create_pending_operation",
                )
                return Answer(
                    text="An error occurred while preparing this request for clarification. Please try again.",
                    confidence=0.0,
                    is_conversational=True,
                    pending_operation=None,
                )

            return Answer(
                text=multi_result.overall_answer,
                confidence=1.0,
                is_conversational=True,
                pending_operation=pending_dict,
                clear_pending=False,
            )

        clear_pending = is_success

        return Answer(
            text=multi_result.overall_answer,
            confidence=confidence,
            is_conversational=True,
            clear_pending=clear_pending,
        )

    def _execute_specialist_step(
        self,
        step: ExecutionStep,
        plan: CognitivePlan,
        resolved_parameters: dict[str, Any],
        prerequisite_results: dict[str, StepExecutionResult],
        question: Question,
        context: ConversationContext | None,
    ) -> StepExecutionResult:
        """
        Specialist execution bridge satisfying StepExecutor protocol.
        Dispatches individual step to the corresponding specialist and returns StepExecutionResult.
        """
        try:
            if step.agent == TargetAgent.CALENDAR_AGENT:
                return self._execute_calendar_step(step, plan, resolved_parameters, question, context)

            if (
                step.agent == TargetAgent.REMINDER_SERVICE
                or (
                    step.agent == TargetAgent.OPERATIONS_AGENT
                    and ("reminder" in step.action.lower() or "schedule_reminder" in step.action.lower())
                )
            ):
                return self._execute_reminder_step(step, plan, resolved_parameters, question, context)

            if step.agent == TargetAgent.GOVERNANCE_AGENT:
                return self._execute_governance_step(step, plan, resolved_parameters, question, context)

            if step.agent == TargetAgent.OPERATIONS_AGENT:
                return self._execute_task_step(step, plan, resolved_parameters, question, context)

            if step.agent == TargetAgent.KNOWLEDGE_AGENT:
                return self._execute_knowledge_step(step, plan, resolved_parameters, question, context)

            if step.agent == TargetAgent.GENERAL_REASONER:
                ans = self._question_answering.answer(question)
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.SUCCEEDED,
                    entity_id=None,
                    entity_type="reasoning_answer",
                    output_fields={},
                    answer=ans.text,
                )

            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=f"Unsupported specialist target '{step.agent.value}'.",
                answer=f"⚠️ Specialist target '{step.agent.value}' is not supported for action dispatch.",
            )
        except Exception as exc:
            logger.exception("Specialist execution bridge caught unexpected error on step '%s': %s", step.step_id, exc)
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Specialist raised unhandled error.",
                answer=f"⚠️ Failed to execute step '{step.step_id}' due to an internal specialist error.",
            )

    def _execute_knowledge_step(
        self,
        step: ExecutionStep,
        plan: CognitivePlan,
        parameters: dict[str, Any],
        question: Question,
        context: ConversationContext | None,
    ) -> StepExecutionResult:
        evidence: list[str] = []
        if self._knowledge_agent is not None and hasattr(self._knowledge_agent, "retrieve_evidence"):
            evidence = self._knowledge_agent.retrieve_evidence(question)
        ans_text = "\n".join(evidence) if evidence else "No knowledge base records found."
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.SUCCEEDED,
            entity_id=None,
            entity_type="knowledge_evidence",
            output_fields={"evidence_count": len(evidence)},
            answer=ans_text,
        )

    def _execute_task_step(
        self,
        step: ExecutionStep,
        plan: CognitivePlan,
        parameters: dict[str, Any],
        question: Question,
        context: ConversationContext | None,
    ) -> StepExecutionResult:
        if self._operations_agent is None:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Operations Agent is not configured.",
                answer="I cannot perform the task operation because the Operations Agent is not configured.",
            )

        params = dict(parameters)
        action_name = step.action
        action_type = step.action_type

        summary = (
            params.get("summary")
            or params.get("task_summary")
            or plan.entities.task_summary
        )
        assignee = (
            params.get("assignee")
            or params.get("owner_name")
            or (plan.entities.employee_names[0] if plan.entities.employee_names else None)
        )
        owner_id = (
            params.get("owner_id")
            or params.get("target_user_id")
            or plan.entities.target_user_id
        )
        priority = params.get("priority") or params.get("severity")
        due_at = (
            params.get("due_at")
            or params.get("due_date")
            or params.get("deadline")
            or (plan.entities.dates[0] if plan.entities.dates else None)
        )
        task_id = (
            params.get("task_id")
            or params.get("item_id")
            or params.get("target_item_id")
            or params.get("item_reference")
            or plan.entities.item_reference
        )
        status = params.get("status")

        # Validate priority if explicitly supplied
        priority_str: str | None = None
        if priority:
            priority_str = str(priority).strip().lower()
            if priority_str not in ("low", "medium", "high", "critical"):
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error=f"Invalid priority '{priority}'.",
                    answer=f"Invalid priority '{priority}'. Supported priorities are low, medium, high, and critical.",
                )

        # Determine operation type and validate mandatory parameters
        is_completion = (
            action_name in ("complete_task", "complete")
            or str(status).lower() in ("completed", "done", "finished", "resolved")
            or params.get("action") == "complete"
        )
        is_update = (
            action_type == ActionType.UPDATE
            or "update" in action_name
            or is_completion
        )

        if is_completion:
            event_type = OrganizationEventType.TASK_COMPLETED
            if not task_id or not str(task_id).strip():
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action="clarify",
                    status=StepExecutionStatus.PENDING,
                    output_fields={"requires_clarification": True},
                    error="task_id",
                    answer="Which task would you like to complete? Please provide the task ID or reference.",
                )
        elif is_update:
            event_type = OrganizationEventType.TASK_UPDATED
            if not task_id or not str(task_id).strip():
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action="clarify",
                    status=StepExecutionStatus.PENDING,
                    output_fields={"requires_clarification": True},
                    error="task_id",
                    answer="Which task would you like to update? Please provide the task ID or reference.",
                )
        else:
            event_type = OrganizationEventType.TASK_CREATED
            if not summary or not str(summary).strip():
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action="clarify",
                    status=StepExecutionStatus.PENDING,
                    output_fields={"requires_clarification": True},
                    error="summary",
                    answer="What is the task description or summary?",
                )

        # Build metadata for observation
        meta: dict[str, Any] = {}
        if assignee:
            meta["assignee"] = assignee
            meta["owner_name"] = assignee
        if owner_id:
            meta["owner_id"] = owner_id
            meta["user_id"] = owner_id
        if priority_str:
            meta["priority"] = priority_str
        if due_at:
            meta["due_at"] = due_at
        if status:
            meta["status"] = status
        if task_id:
            cleaned_id = str(task_id).strip()
            meta["item_id"] = cleaned_id
            meta["task_id"] = cleaned_id

        effective_summary = (
            str(summary).strip()
            if (summary and str(summary).strip())
            else (f"Update task {task_id}" if task_id else "Task mutation")
        )

        evidence = [question.text] if question.text else ["cognitive plan execution"]
        obs = Observation(
            observation_type=ObservationType.TASK,
            summary=effective_summary,
            evidence=evidence,
            confidence=plan.intent_confidence,
            metadata=meta,
        )

        correlation_id_val = (
            Identifier(business_id=plan.request_id)
            if plan.request_id
            else None
        )

        event = OrganizationEvent(
            event_type=event_type,
            summary=effective_summary,
            observations=[obs],
            confidence=plan.intent_confidence,
            correlation_id=correlation_id_val,
            occurred_at=datetime.now(timezone.utc),
        )

        step_scoped_id = f"{plan.request_id}:{step.step_id}" if plan.request_id and step.step_id else (plan.request_id or "")
        try:
            result = self._operations_agent.process_event(
                event,
                source_type="cognitive_engine",
                source_event_id=step_scoped_id,
                correlation_id=step_scoped_id,
                raise_on_unsupported=True,
            )
        except InvalidLifecycleTransitionError as err:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=f"Cannot transition task: {err}",
                answer=f"Cannot transition task: {err}",
            )
        except UnsupportedOperationalEventError as err:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=f"Task action is not supported: {err}",
                answer=f"Task action is not supported: {err}",
            )
        except OperationalItemNotFoundError as err:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=f"Task not found: {err}",
                answer=f"Task not found: {err}",
            )
        except OperationalError as err:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=f"Task operation failed: {err}",
                answer=f"Task operation failed: {err}",
            )
        except Exception as err:
            logger.exception("Unexpected error during task action dispatch: %s", err)
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=str(err),
                answer="An unexpected error occurred while processing the task operation.",
            )

        if result.operation == "created":
            item_id = result.affected_item_id or (
                str(result.item.identifier.graph_id) if result.item else ""
            )
            status_val = result.status.value if result.status else "open"
            item_summary = result.item.summary if result.item else effective_summary
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.SUCCEEDED,
                entity_id=item_id,
                entity_type="task",
                output_fields={
                    "task_id": item_id,
                    "entity_id": item_id,
                    "summary": item_summary,
                    "status": status_val,
                },
                answer=f"Task created successfully: *{item_summary}* (ID: `{item_id}`). Status: {status_val}.",
                warnings=result.warnings,
                domain_result=result,
            )
        elif result.operation == "updated":
            item_id = result.affected_item_id or (
                str(result.item.identifier.graph_id) if result.item else ""
            )
            status_val = result.status.value if result.status else "in_progress"
            item_summary = result.item.summary if result.item else effective_summary
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.SUCCEEDED,
                entity_id=item_id,
                entity_type="task",
                output_fields={
                    "task_id": item_id,
                    "entity_id": item_id,
                    "summary": item_summary,
                    "status": status_val,
                },
                answer=f"Task updated successfully: *{item_summary}* (ID: `{item_id}`). Status: {status_val}.",
                warnings=result.warnings,
                domain_result=result,
            )
        elif result.operation == "completed":
            item_id = result.affected_item_id or (
                str(result.item.identifier.graph_id) if result.item else ""
            )
            item_summary = result.item.summary if result.item else effective_summary
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.SUCCEEDED,
                entity_id=item_id,
                entity_type="task",
                output_fields={
                    "task_id": item_id,
                    "entity_id": item_id,
                    "summary": item_summary,
                    "status": "completed",
                },
                answer=f"Task completed successfully: *{item_summary}* (ID: `{item_id}`).",
                warnings=result.warnings,
                domain_result=result,
            )
        elif result.operation == "no_op" or result.idempotent:
            item_id = result.affected_item_id or (
                str(result.item.identifier.graph_id) if result.item else ""
            )
            status_val = result.status.value if result.status else "current"
            item_summary = result.item.summary if result.item else effective_summary
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.SUCCEEDED,
                entity_id=item_id,
                entity_type="task",
                output_fields={
                    "task_id": item_id,
                    "entity_id": item_id,
                    "summary": item_summary,
                    "status": status_val,
                },
                answer=f"Task '{item_summary}' (ID: `{item_id}`) is already in status {status_val}. No changes were made.",
                warnings=result.warnings,
                domain_result=result,
            )
        else:
            warning_msg = (
                "; ".join(result.warnings)
                if result.warnings
                else "Operation was ignored by domain rules."
            )
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=warning_msg,
                answer=f"Task operation was not performed: {warning_msg}",
                warnings=result.warnings,
                domain_result=result,
            )

    def _execute_calendar_step(
        self,
        step: ExecutionStep,
        plan: CognitivePlan,
        parameters: dict[str, Any],
        question: Question,
        context: ConversationContext | None,
    ) -> StepExecutionResult:
        if self._calendar_agent is None:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Calendar service unavailable.",
                answer="⚠️ Calendar service is currently unavailable.",
            )

        # 1. Resolve authenticated requester identity
        user_id = ""
        if context and context.user_id:
            user_id = str(context.user_id).strip()
        elif question.target_user_id:
            user_id = str(question.target_user_id).strip()

        if not user_id:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Requester identity required.",
                answer="⚠️ Requester identity is required to perform calendar actions.",
            )

        channel_id = str(context.channel_id).strip() if context and context.channel_id else ""

        # 2. Extract step parameters and action
        step_params = dict(parameters)
        action_type = step.action_type
        action_name = step.action

        # Merge extracted entities into parameters if missing
        merged_params = dict(step_params)
        if plan.entities:
            if not merged_params.get("title") and plan.entities.event_title:
                merged_params["title"] = plan.entities.event_title
            if not merged_params.get("dates") and plan.entities.dates:
                merged_params["dates"] = plan.entities.dates
            if not merged_params.get("times") and plan.entities.times:
                merged_params["times"] = plan.entities.times
            if not merged_params.get("duration_minutes") and plan.entities.duration_minutes:
                merged_params["duration_minutes"] = plan.entities.duration_minutes
            if not merged_params.get("audience_type") and plan.entities.audience_type:
                merged_params["audience_type"] = plan.entities.audience_type
            if not merged_params.get("audience_identifier") and plan.entities.audience_id:
                merged_params["audience_identifier"] = plan.entities.audience_id
            if not merged_params.get("item_reference") and plan.entities.item_reference:
                merged_params["item_reference"] = plan.entities.item_reference
            if plan.entities.extra_params:
                for k, v in plan.entities.extra_params.items():
                    if k not in merged_params:
                        merged_params[k] = v

        is_cancel = (
            action_type == ActionType.CANCEL
            or "cancel" in action_name.lower()
            or "delete" in action_name.lower()
        )
        is_update = (
            action_type == ActionType.UPDATE
            or "update" in action_name.lower()
            or "reschedule" in action_name.lower()
        )
        is_create = not is_cancel and not is_update

        # Check sufficiency of parameters for structured execution
        has_sufficient_structured = False
        entry_id_val = merged_params.get("entry_id") or merged_params.get("item_reference")
        if is_cancel or is_update:
            has_sufficient_structured = bool(user_id) and bool(entry_id_val and str(entry_id_val).strip())
        elif is_create:
            has_title = bool(merged_params.get("title") or merged_params.get("event_title") or merged_params.get("summary"))
            has_time = bool(
                merged_params.get("start_time")
                or (merged_params.get("dates") and merged_params.get("times"))
                or (merged_params.get("date") and merged_params.get("time"))
            )
            has_aud = bool(
                merged_params.get("audience_type")
                and (
                    merged_params.get("audience_identifier")
                    or merged_params.get("audience_id")
                    or str(merged_params.get("audience_type")).lower() == "organization"
                )
            )
            has_sufficient_structured = bool(user_id) and has_title and has_time and has_aud

        # PRIORITY 1: Structured Execution
        if has_sufficient_structured and hasattr(self._calendar_agent, "execute_structured"):
            action_verb = "cancel" if is_cancel else ("update" if is_update else "create")
            try:
                entry = None
                if action_verb == "create" and hasattr(self._calendar_agent, "create_entry_structured"):
                    entry = self._calendar_agent.create_entry_structured(merged_params, user_id=user_id)
                    conf = self._calendar_agent.format_confirmation(entry, operation="create")
                elif action_verb == "update" and hasattr(self._calendar_agent, "update_entry_structured"):
                    entry = self._calendar_agent.update_entry_structured(merged_params, user_id=user_id)
                    conf = self._calendar_agent.format_confirmation(entry, operation="update")
                elif action_verb == "cancel" and hasattr(self._calendar_agent, "cancel_entry_structured"):
                    entry = self._calendar_agent.cancel_entry_structured(merged_params, user_id=user_id)
                    conf = self._calendar_agent.format_confirmation(entry, operation="cancel")
                else:
                    conf = self._calendar_agent.execute_structured(
                        action_verb,
                        merged_params,
                        user_id=user_id,
                    )

                entry_id_res = entry.entry_id if entry else str(merged_params.get("entry_id") or merged_params.get("item_reference") or "")
                out_fields: dict[str, Any] = {}
                if entry:
                    out_fields = {
                        "entry_id": entry.entry_id,
                        "entity_id": entry.entry_id,
                        "title": entry.title,
                        "status": entry.status.value,
                    }
                elif entry_id_res:
                    out_fields = {"entry_id": entry_id_res, "entity_id": entry_id_res}

                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.SUCCEEDED,
                    entity_id=entry_id_res or None,
                    entity_type="calendar_entry",
                    output_fields=out_fields,
                    answer=conf,
                    domain_result=entry,
                )
            except UnauthorizedCalendarActionError:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error="Unauthorized calendar action.",
                    answer="I can't perform this calendar action because you are not authorized. Only the creator can modify or cancel it.",
                )
            except (InvalidCalendarEntryError, InvalidTimeRangeError, InvalidAudienceError, CalendarEntryNotFoundError) as err:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error=str(err),
                    answer=f"⚠️ I couldn't execute the calendar action: {err}",
                )
            except CalendarDomainError as err:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error=str(err),
                    answer=f"⚠️ Calendar action failed: {err}",
                )
            except Exception as err:
                logger.exception("Unexpected error during structured calendar execution: %s", err)
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error=str(err),
                    answer="⚠️ I ran into an error while processing the calendar entry. Please try again.",
                )

        # PRIORITY 2: Natural-Language Fallback (handle_message)
        cal_resp: str | None = None
        if hasattr(self._calendar_agent, "handle_message"):
            cal_resp = self._calendar_agent.handle_message(
                question.text,
                user_id=user_id,
                channel_id=channel_id,
            )
            if cal_resp is None and plan.execution_steps:
                dates_str = merged_params.get("dates", ["tomorrow"])[0] if merged_params.get("dates") else "tomorrow"
                times_str = merged_params.get("times", ["9am"])[0] if merged_params.get("times") else "9am"
                title_str = merged_params.get("title") or "Meeting"
                reconstructed = f"Schedule {title_str} on {dates_str} at {times_str}"
                cal_resp = self._calendar_agent.handle_message(
                    reconstructed,
                    user_id=user_id,
                    channel_id=channel_id,
                )

        if cal_resp is not None:
            is_confirmed = any(
                phrase in cal_resp.lower()
                for phrase in (
                    "done!",
                    "successfully",
                    "scheduled",
                    "updated",
                    "cancelled",
                    "i've added",
                    "i've updated",
                    "i've cancelled",
                )
            )
            is_rejected = any(
                phrase in cal_resp.lower()
                for phrase in (
                    "can't",
                    "cannot",
                    "not authorized",
                    "couldn't find",
                    "what is the",
                    "who is",
                    "error",
                    "failed",
                )
            )
            if is_confirmed and not is_rejected:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.SUCCEEDED,
                    answer=cal_resp,
                )
            else:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error="Calendar natural language operation not confirmed.",
                    answer=cal_resp,
                )

        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.FAILED,
            error="Missing parameters for calendar execution.",
            answer=(
                "⚠️ I understood you wanted to perform a calendar action, but I need more details to complete it. "
                "Please provide the title, date, time, and intended audience (or entry ID for updates/cancellations)."
            ),
        )

    def _execute_reminder_step(
        self,
        step: ExecutionStep,
        plan: CognitivePlan,
        parameters: dict[str, Any],
        question: Question,
        context: ConversationContext | None,
    ) -> StepExecutionResult:
        # 1. Check reminder service availability
        if self._operations_agent is None or getattr(self._operations_agent, "reminder_service", None) is None:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Reminder service unavailable.",
                answer="⚠️ Reminder service is currently unavailable.",
            )

        # 2. Authenticated requester identity
        user_id = ""
        if context and context.user_id:
            user_id = str(context.user_id).strip()
        elif question.target_user_id:
            user_id = str(question.target_user_id).strip()

        if not user_id:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Requester identity required.",
                answer="⚠️ Requester identity is required to perform reminder actions.",
            )

        # 3. Extract step parameters and fallback to plan entities
        step_params = dict(parameters)
        if plan.entities:
            if not step_params.get("task_id") and not step_params.get("item_reference"):
                if plan.entities.item_reference:
                    step_params["task_id"] = plan.entities.item_reference
            if not step_params.get("target_user_id") and not step_params.get("assignee"):
                if plan.entities.target_user_id:
                    step_params["target_user_id"] = plan.entities.target_user_id
                elif plan.entities.employee_names:
                    step_params["target_user_id"] = plan.entities.employee_names[0]
            if not step_params.get("times") and plan.entities.times:
                step_params["times"] = plan.entities.times

        # 4. Check for unsupported one-time reminder / timer requests
        raw_text = question.text.lower() if question.text else ""
        is_one_time = (
            step_params.get("one_time") is True
            or step_params.get("timer") is True
            or str(step_params.get("type", "")).lower() in ("one_time", "timer", "once", "single")
            or "duration_minutes" in step_params
            or bool(
                re.search(
                    r"\b(?:in\s+\d+\s*(?:mins?|minutes?|hours?|secs?|seconds?)|set\s+(?:a\s+)?timer|timer\s+for|one[- ]time\s+reminder|remind\s+me\s+once)\b",
                    raw_text,
                )
            )
        )
        if is_one_time:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="One-time reminders not supported.",
                answer=(
                    "⚠️ POLIS currently only supports daily recurring task check-in reminders "
                    "(configured with two daily check-in times) linked to an existing operational task. "
                    "One-time reminders and generic timers are not currently supported."
                ),
            )

        # 5. Validate Task ID
        task_id = str(step_params.get("task_id") or step_params.get("item_reference") or "").strip()
        if not task_id:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Valid task ID required.",
                answer="⚠️ Cannot schedule task reminder: a valid task ID is required.",
            )

        task = self._operations_agent.get_task(task_id)
        if task is None:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=f"Task '{task_id}' was not found.",
                answer=f"⚠️ Cannot schedule task reminder: task '{task_id}' was not found.",
            )

        if task.status in (
            OperationalItemStatus.COMPLETED,
            OperationalItemStatus.CANCELLED,
            OperationalItemStatus.CLOSED,
        ):
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=f"Task '{task_id}' is in status '{task.status.value}'.",
                answer=(
                    f"⚠️ Cannot schedule reminder for task '{task_id}' because it is in status '{task.status.value}'. "
                    "Reminders can only be scheduled for open tasks."
                ),
            )

        # 6. Validate Target User
        target_user_id = str(step_params.get("target_user_id") or step_params.get("assignee") or "").strip()
        if not target_user_id and task.owner_id and str(task.owner_id).strip():
            target_user_id = str(task.owner_id).strip()

        if not target_user_id:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Target user required.",
                answer="⚠️ Cannot schedule task reminder: target user is required.",
            )

        # 7. Validate Channel Context
        channel_id = str(
            step_params.get("channel_id")
            or (context.channel_id if context and context.channel_id else "")
        ).strip()
        if not channel_id:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Slack channel context required.",
                answer="⚠️ Cannot schedule task reminder: Slack channel context is required.",
            )

        # 8. Validate Source Message Timestamp
        source_message_ts = str(
            step_params.get("source_message_ts")
            or step_params.get("message_ts")
            or (context.thread_ts if context and context.thread_ts else "")
        ).strip()
        if not source_message_ts:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Source message timestamp required.",
                answer="⚠️ Cannot schedule task reminder: source message timestamp is required.",
            )
        source_thread_ts = (
            str(step_params.get("source_thread_ts") or (context.thread_ts if context and context.thread_ts else "")).strip()
            or None
        )

        # 9. Validate Reminder Times
        raw_times = step_params.get("times")
        time_1 = step_params.get("time_1")
        time_2 = step_params.get("time_2")

        if isinstance(raw_times, list) and raw_times:
            if not time_1 and len(raw_times) >= 1:
                time_1 = str(raw_times[0]).strip()
            if not time_2 and len(raw_times) >= 2:
                time_2 = str(raw_times[1]).strip()

        if not time_1:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Reminder times required.",
                answer="⚠️ Cannot schedule task reminder: reminder times are required (e.g., '09:00' and '17:00').",
            )

        if not time_2:
            time_2 = "17:00"

        time_1_str = str(time_1).strip()
        time_2_str = str(time_2).strip()
        try:
            time.fromisoformat(time_1_str)
        except ValueError:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=f"Invalid time_1 '{time_1_str}'.",
                answer=f"⚠️ Cannot schedule task reminder: reminder time '{time_1_str}' is invalid. Use HH:MM 24-hour format (e.g., '09:00').",
            )

        try:
            time.fromisoformat(time_2_str)
        except ValueError:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=f"Invalid time_2 '{time_2_str}'.",
                answer=f"⚠️ Cannot schedule task reminder: reminder time '{time_2_str}' is invalid. Use HH:MM 24-hour format (e.g., '17:00').",
            )

        # 10. Validate Timezone
        timezone_name = str(
            step_params.get("timezone_name")
            or step_params.get("timezone")
            or "UTC"
        ).strip()
        try:
            ZoneInfo(timezone_name)
        except Exception:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=f"Invalid timezone '{timezone_name}'.",
                answer=f"⚠️ Cannot schedule task reminder: timezone '{timezone_name}' is invalid.",
            )

        # 11. Duplicate Idempotent Scheduling Protection
        existing = None
        if hasattr(self._operations_agent, "find_task_reminder"):
            existing = self._operations_agent.find_task_reminder(task_id, target_user_id)
        elif hasattr(self._operations_agent, "find_active_task_reminder"):
            existing = self._operations_agent.find_active_task_reminder(task_id, target_user_id)
        elif self._operations_agent is not None and getattr(self._operations_agent, "_reminder_service", None) is not None:
            svc = self._operations_agent._reminder_service
            if hasattr(svc, "get_by_task_and_user"):
                existing = svc.get_by_task_and_user(task_id, target_user_id)
            elif hasattr(svc, "find_active_for_target"):
                for r in svc.find_active_for_target(target_user_id):
                    if getattr(r, "task", None) == task.summary and getattr(r, "active", True):
                        existing = r
                        break

        if existing is not None:
            rem_id = str(existing.identifier.graph_id)
            sched_times = (
                f"{existing.schedule.time_1} and {existing.schedule.time_2} ({existing.schedule.timezone})"
                if hasattr(existing, "schedule") and existing.schedule
                else (
                    f"Next check-in: {existing.next_reminder_at.isoformat()}"
                    if hasattr(existing, "next_reminder_at") and existing.next_reminder_at
                    else f"{time_1_str} and {time_2_str} ({timezone_name})"
                )
            )
            status_val = (
                existing.status.value
                if hasattr(existing, "status") and hasattr(existing.status, "value")
                else ("active" if getattr(existing, "active", True) else "inactive")
            )
            ch_id = getattr(existing, "channel_id", channel_id)
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.SUCCEEDED,
                entity_id=rem_id,
                entity_type="reminder",
                output_fields={
                    "reminder_id": rem_id,
                    "task_id": task_id,
                    "entity_id": rem_id,
                    "target_user_id": target_user_id,
                },
                answer=(
                    f"A reminder schedule already exists for task *{task.summary}* (`{task_id}`) "
                    f"and user `{target_user_id}`.\n\n"
                    f"ℹ️ Current configuration:\n"
                    f"• *Reminder ID:* `{rem_id}`\n"
                    f"• *Daily Check-in Times:* {sched_times}\n"
                    f"• *Status:* {status_val}\n"
                    f"• *Channel:* `{ch_id}`"
                ),
                domain_result=existing,
            )

        # 12. Execute scheduling via OperationsAgent
        try:
            reminder = self._operations_agent.schedule_task_reminder(
                task_id=task_id,
                target_user_id=target_user_id,
                creator_user_id=user_id,
                channel_id=channel_id,
                source_message_ts=source_message_ts,
                source_thread_ts=source_thread_ts,
                timezone_name=timezone_name,
                time_1=time_1_str,
                time_2=time_2_str,
            )
            if reminder is not None:
                rem_id = str(reminder.identifier.graph_id)
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.SUCCEEDED,
                    entity_id=rem_id,
                    entity_type="reminder",
                    output_fields={
                        "reminder_id": rem_id,
                        "task_id": task_id,
                        "entity_id": rem_id,
                        "target_user_id": target_user_id,
                    },
                    answer=(
                        f"Done! I've scheduled daily reminders for task *{task.summary}* (`{task_id}`).\n\n"
                        f"✅ Successfully scheduled task reminder:\n"
                        f"• *Task:* {task.summary}\n"
                        f"• *Target User:* `{target_user_id}`\n"
                        f"• *Creator:* `{user_id}`\n"
                        f"• *Daily Check-in Times:* {time_1_str} and {time_2_str} ({timezone_name})\n"
                        f"• *Channel:* `{channel_id}`"
                    ),
                    domain_result=reminder,
                )
            else:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error="Reminder service unavailable.",
                    answer="⚠️ Reminder service is currently unavailable.",
                )
        except OperationalItemNotFoundError as err:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=str(err),
                answer=f"⚠️ Cannot schedule task reminder: {err}",
            )
        except (InvalidLifecycleTransitionError, OperationalError) as err:
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=str(err),
                answer=f"⚠️ Cannot schedule task reminder: {err}",
            )
        except Exception as err:
            logger.exception("Unexpected error during reminder dispatch: %s", err)
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error=str(err),
                answer="⚠️ An unexpected error occurred while scheduling the reminder. Please try again.",
            )

    def _execute_governance_step(
        self,
        step: ExecutionStep,
        plan: CognitivePlan,
        parameters: dict[str, Any],
        question: Question,
        context: ConversationContext | None,
    ) -> StepExecutionResult:
        # 1. Verify GovernanceAgent availability
        if self._governance_agent is None or not getattr(self._governance_agent, "enabled", True):
            return StepExecutionResult(
                step_id=step.step_id,
                agent=step.agent,
                action=step.action,
                status=StepExecutionStatus.FAILED,
                error="Governance Agent unavailable.",
                answer="⚠️ Governance Agent is not available or disabled by configuration.",
            )

        # 2. Extract step parameters and action
        step_params = dict(parameters)
        action_name = step.action.lower().strip()
        action_type = step.action_type

        # Merge extracted entities from plan into parameters as fallback only
        if plan.entities:
            if not step_params.get("title") and (plan.entities.task_summary or plan.entities.event_title):
                step_params["title"] = plan.entities.task_summary or plan.entities.event_title
            if not step_params.get("target_object") and plan.entities.item_reference:
                step_params["target_object"] = plan.entities.item_reference
            if not step_params.get("approval_id") and plan.entities.item_reference:
                step_params["approval_id"] = plan.entities.item_reference
            if plan.entities.extra_params:
                for k, v in plan.entities.extra_params.items():
                    if k not in step_params and v:
                        step_params[k] = v

        # Determine operation category
        is_request = (
            action_type == ActionType.CREATE
            or any(w in action_name for w in ("request", "create", "submit", "ask"))
        )
        is_reject = (
            not is_request
            and any(w in action_name for w in ("reject", "deny"))
        )
        is_grant = (
            not is_request
            and not is_reject
            and (any(w in action_name for w in ("grant", "approve")) or action_type == ActionType.UPDATE)
        )

        # ---------------------------------------------------------------------
        # OPERATION 1: REQUEST APPROVAL (CREATE)
        # ---------------------------------------------------------------------
        if is_request:
            requester_id = ""
            if context and context.user_id:
                requester_id = str(context.user_id).strip()
            elif question.target_user_id:
                requester_id = str(question.target_user_id).strip()

            if not requester_id:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error="Requester identity required.",
                    answer="⚠️ Requester identity is required to request approvals.",
                )

            title = str(step_params.get("title") or step_params.get("description") or "").strip()
            if not title:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error="Title required.",
                    answer="⚠️ Cannot request approval: a valid title or description is required.",
                )

            target_object = str(
                step_params.get("target_object")
                or step_params.get("target_item_id")
                or step_params.get("affected_object")
                or step_params.get("target")
                or step_params.get("resource")
                or ""
            ).strip()
            if not target_object:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error="Target object required.",
                    answer="⚠️ Cannot request approval: a valid target object or resource is required.",
                )

            raw_policy_id = step_params.get("policy_id")
            policy_id_val: str | None = None
            if raw_policy_id and str(raw_policy_id).strip():
                policy_id_val = str(raw_policy_id).strip()
                policy = self._governance_agent.get_policy(policy_id_val)
                if policy is None:
                    return StepExecutionResult(
                        step_id=step.step_id,
                        agent=step.agent,
                        action=step.action,
                        status=StepExecutionStatus.FAILED,
                        error=f"Policy '{policy_id_val}' not found.",
                        answer=f"⚠️ Cannot request approval: policy '{policy_id_val}' was not found.",
                    )

            correlation_id_val = str(step_params.get("correlation_id", "")).strip() or None
            notes_val = str(step_params.get("notes", "")).strip()

            try:
                approval = self._governance_agent.request_approval(
                    title=title,
                    target_object=target_object,
                    requester_id=requester_id,
                    policy_id=policy_id_val,
                    correlation_id=correlation_id_val,
                    notes=notes_val,
                )
                response_lines = [
                    "✅ Approval request submitted successfully.",
                    f"• ID: {approval.id}",
                    f"• Title: {approval.title}",
                    f"• Target Object: {approval.target_object}",
                    f"• Status: {approval.status.value}",
                    f"• Requester: {approval.requester_id}",
                ]
                if approval.policy_id:
                    response_lines.append(f"• Policy ID: {approval.policy_id}")
                if approval.notes:
                    response_lines.append(f"• Notes: {approval.notes}")

                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.SUCCEEDED,
                    entity_id=approval.id,
                    entity_type="approval_request",
                    output_fields={
                        "approval_id": approval.id,
                        "entity_id": approval.id,
                        "title": approval.title,
                        "status": approval.status.value,
                        "target_object": approval.target_object,
                    },
                    answer="\n".join(response_lines),
                    domain_result=approval,
                )
            except Exception as e:
                logger.error("Governance request_approval failed: %s", e, exc_info=True)
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error=str(e),
                    answer=f"⚠️ Approval request failed: {e}",
                )

        # ---------------------------------------------------------------------
        # OPERATION 2 & 3: GRANT OR REJECT APPROVAL (UPDATE)
        # ---------------------------------------------------------------------
        elif is_grant or is_reject:
            approver_id = ""
            if context and context.user_id:
                approver_id = str(context.user_id).strip()
            elif question.target_user_id:
                approver_id = str(question.target_user_id).strip()

            op_label = "grant" if is_grant else "reject"

            if not approver_id:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error="Approver identity required.",
                    answer=f"⚠️ Approver identity is required to {op_label} approvals.",
                )

            approval_id = str(
                step_params.get("approval_id")
                or step_params.get("target_object")
                or step_params.get("item_reference")
                or ""
            ).strip()
            if not approval_id:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error=f"Approval ID required for {op_label}.",
                    answer=f"⚠️ Cannot {op_label} approval: approval ID is required.",
                )

            approval = None
            if hasattr(self._governance_agent, "find_approval"):
                approval = self._governance_agent.find_approval(approval_id)
            elif hasattr(self._governance_agent, "_approval_repository"):
                approval = self._governance_agent._approval_repository.get(approval_id)

            if approval is None:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error=f"Approval request '{approval_id}' was not found.",
                    answer=f"⚠️ Approval request '{approval_id}' was not found.",
                )

            # Strict self-approval rejection
            if approval.requester_id and approver_id == approval.requester_id:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error="Self-approval prohibited.",
                    answer=f"⚠️ Cannot {op_label} approval: self-approval is strictly prohibited. Requester cannot act on their own request.",
                )

            # Strict approver authorization check
            is_authorized = False
            if hasattr(self._governance_agent, "is_authorized_approver"):
                is_authorized = self._governance_agent.is_authorized_approver(approver_id, approval)

            if not is_authorized:
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error="Unauthorized approver.",
                    answer=f"⚠️ Unauthorized: you are not authorized to {op_label} this approval request. Only designated approvers can {op_label} approvals.",
                )

            rejection_reason: str | None = None
            if is_reject:
                rejection_reason = str(
                    step_params.get("reason")
                    or step_params.get("rejection_reason")
                    or step_params.get("notes")
                    or ""
                ).strip()
                if not rejection_reason:
                    return StepExecutionResult(
                        step_id=step.step_id,
                        agent=step.agent,
                        action=step.action,
                        status=StepExecutionStatus.FAILED,
                        error="Rejection reason required.",
                        answer="⚠️ Cannot reject approval: a rejection reason is required.",
                    )

            notes_val = str(step_params.get("notes", "")).strip() or None

            try:
                if is_grant:
                    updated = self._governance_agent.grant_approval(
                        approval_id=approval.id,
                        approver_id=approver_id,
                        notes=notes_val,
                    )
                    action_past = "granted"
                else:
                    updated = self._governance_agent.reject_approval(
                        approval_id=approval.id,
                        approver_id=approver_id,
                        reason=rejection_reason,
                    )
                    action_past = "rejected"

                response_lines = [
                    f"✅ Approval request {action_past} successfully.",
                    f"• ID: {updated.id}",
                    f"• Title: {updated.title}",
                    f"• Status: {updated.status.value}",
                    f"• Approver: {updated.approver_id}",
                ]
                if updated.granted_at:
                    response_lines.append(f"• Granted At: {updated.granted_at.isoformat()}")
                if updated.notes:
                    response_lines.append(f"• Notes: {updated.notes}")

                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.SUCCEEDED,
                    entity_id=updated.id,
                    entity_type="approval_request",
                    output_fields={
                        "approval_id": updated.id,
                        "entity_id": updated.id,
                        "status": updated.status.value,
                    },
                    answer="\n".join(response_lines),
                    domain_result=updated,
                )
            except Exception as e:
                logger.error("Governance %s_approval failed: %s", op_label, e, exc_info=True)
                return StepExecutionResult(
                    step_id=step.step_id,
                    agent=step.agent,
                    action=step.action,
                    status=StepExecutionStatus.FAILED,
                    error=str(e),
                    answer=f"⚠️ Failed to {op_label} approval request '{approval.id}': {e}",
                )

        # ---------------------------------------------------------------------
        # OPERATION 4: UNSUPPORTED GOVERNANCE MUTATION
        # ---------------------------------------------------------------------
        return StepExecutionResult(
            step_id=step.step_id,
            agent=step.agent,
            action=step.action,
            status=StepExecutionStatus.FAILED,
            error=f"Unsupported governance operation '{action_name}'.",
            answer=f"⚠️ Governance operation '{action_name}' is not supported. POLIS only supports requesting, granting, or rejecting approvals.",
        )

    def _dispatch_task_action(
        self,
        plan: CognitivePlan,
        question: Question,
        context: ConversationContext | None,
    ) -> Answer:
        """
        Dispatch a verified task mutation action to the OperationsAgent.
        """
        if self._operations_agent is None:
            return Answer(
                text="I cannot perform the task operation because the Operations Agent is not configured.",
                confidence=0.0,
                is_conversational=True,
                clear_pending=False,
            )

        task_step = None
        for step in plan.execution_steps:
            if step.agent == TargetAgent.OPERATIONS_AGENT:
                task_step = step
                break
        if task_step is None and plan.execution_steps:
            task_step = plan.execution_steps[0]

        params = dict(task_step.parameters) if task_step else {}
        action_name = task_step.action if task_step else "create_task"
        action_type = task_step.action_type if task_step else ActionType.CREATE

        summary = (
            params.get("summary")
            or params.get("task_summary")
            or plan.entities.task_summary
        )
        assignee = (
            params.get("assignee")
            or params.get("owner_name")
            or (plan.entities.employee_names[0] if plan.entities.employee_names else None)
        )
        owner_id = (
            params.get("owner_id")
            or params.get("target_user_id")
            or plan.entities.target_user_id
        )
        priority = params.get("priority") or params.get("severity")
        due_at = (
            params.get("due_at")
            or params.get("due_date")
            or params.get("deadline")
            or (plan.entities.dates[0] if plan.entities.dates else None)
        )
        task_id = (
            params.get("task_id")
            or params.get("item_id")
            or params.get("target_item_id")
            or params.get("item_reference")
            or plan.entities.item_reference
        )
        status = params.get("status")

        # Validate priority if explicitly supplied
        priority_str: str | None = None
        if priority:
            priority_str = str(priority).strip().lower()
            if priority_str not in ("low", "medium", "high", "critical"):
                return Answer(
                    text=f"Invalid priority '{priority}'. Supported priorities are low, medium, high, and critical.",
                    confidence=0.0,
                    is_conversational=True,
                    clear_pending=False,
                )

        # Determine operation type and validate mandatory parameters
        is_completion = (
            action_name in ("complete_task", "complete")
            or str(status).lower() in ("completed", "done", "finished", "resolved")
            or params.get("action") == "complete"
        )
        is_update = (
            action_type == ActionType.UPDATE
            or "update" in action_name
            or is_completion
        )

        if is_completion:
            event_type = OrganizationEventType.TASK_COMPLETED
            if not task_id or not str(task_id).strip():
                return Answer(
                    text="Which task would you like to complete? Please provide the task ID or reference.",
                    confidence=0.0,
                    is_conversational=True,
                    clear_pending=False,
                )
        elif is_update:
            event_type = OrganizationEventType.TASK_UPDATED
            if not task_id or not str(task_id).strip():
                return Answer(
                    text="Which task would you like to update? Please provide the task ID or reference.",
                    confidence=0.0,
                    is_conversational=True,
                    clear_pending=False,
                )
        else:
            event_type = OrganizationEventType.TASK_CREATED
            if not summary or not str(summary).strip():
                return Answer(
                    text="What is the task description or summary?",
                    confidence=0.0,
                    is_conversational=True,
                    clear_pending=False,
                )

        # Build metadata for observation
        meta: dict[str, Any] = {}
        if assignee:
            meta["assignee"] = assignee
            meta["owner_name"] = assignee
        if owner_id:
            meta["owner_id"] = owner_id
            meta["user_id"] = owner_id
        if priority_str:
            meta["priority"] = priority_str
        if due_at:
            meta["due_at"] = due_at
        if status:
            meta["status"] = status
        if task_id:
            cleaned_id = str(task_id).strip()
            meta["item_id"] = cleaned_id
            meta["task_id"] = cleaned_id

        effective_summary = (
            str(summary).strip()
            if (summary and str(summary).strip())
            else (f"Update task {task_id}" if task_id else "Task mutation")
        )

        evidence = [question.text] if question.text else ["cognitive plan execution"]
        obs = Observation(
            observation_type=ObservationType.TASK,
            summary=effective_summary,
            evidence=evidence,
            confidence=plan.intent_confidence,
            metadata=meta,
        )

        correlation_id_val = (
            Identifier(business_id=plan.request_id)
            if plan.request_id
            else None
        )

        event = OrganizationEvent(
            event_type=event_type,
            summary=effective_summary,
            observations=[obs],
            confidence=plan.intent_confidence,
            correlation_id=correlation_id_val,
            occurred_at=datetime.now(timezone.utc),
        )

        try:
            result = self._operations_agent.process_event(
                event,
                source_type="cognitive_engine",
                source_event_id=plan.request_id,
                correlation_id=plan.request_id,
                raise_on_unsupported=True,
            )
        except InvalidLifecycleTransitionError as err:
            return Answer(
                text=f"Task lifecycle transition rejected: {err}",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )
        except OperationalItemNotFoundError as err:
            return Answer(
                text=f"Task not found: {err}",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )
        except UnsupportedOperationalEventError as err:
            return Answer(
                text=f"Unsupported task operation: {err}",
                confidence=0.0,
                is_conversational=True,
                clear_pending=False,
            )
        except OperationalError as err:
            return Answer(
                text=f"Task operation failed: {err}",
                confidence=0.0,
                is_conversational=True,
                clear_pending=False,
            )
        except Exception as err:
            logger.exception("Unexpected error dispatching task action: %s", err)
            return Answer(
                text="An unexpected error occurred while processing the task operation.",
                confidence=0.0,
                is_conversational=True,
                clear_pending=False,
            )

        if result.operation == "created":
            item_id = result.affected_item_id or (
                str(result.item.identifier.graph_id) if result.item else ""
            )
            status_val = result.status.value if result.status else "open"
            item_summary = result.item.summary if result.item else effective_summary
            return Answer(
                text=f"Task created successfully: *{item_summary}* (ID: `{item_id}`). Status: {status_val}.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=True,
            )
        elif result.operation == "updated":
            item_id = result.affected_item_id or (
                str(result.item.identifier.graph_id) if result.item else ""
            )
            status_val = result.status.value if result.status else "in_progress"
            item_summary = result.item.summary if result.item else effective_summary
            return Answer(
                text=f"Task updated successfully: *{item_summary}* (ID: `{item_id}`). Status: {status_val}.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=True,
            )
        elif result.operation == "completed":
            item_id = result.affected_item_id or (
                str(result.item.identifier.graph_id) if result.item else ""
            )
            item_summary = result.item.summary if result.item else effective_summary
            return Answer(
                text=f"Task completed successfully: *{item_summary}* (ID: `{item_id}`).",
                confidence=1.0,
                is_conversational=True,
                clear_pending=True,
            )
        elif result.operation == "no_op" or result.idempotent:
            item_id = result.affected_item_id or (
                str(result.item.identifier.graph_id) if result.item else ""
            )
            status_val = result.status.value if result.status else "current"
            item_summary = result.item.summary if result.item else effective_summary
            return Answer(
                text=f"Task '{item_summary}' (ID: `{item_id}`) is already in status {status_val}. No changes were made.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=True,
            )
        else:
            warning_msg = (
                "; ".join(result.warnings)
                if result.warnings
                else "Operation was ignored by domain rules."
            )
            return Answer(
                text=f"Task operation was not performed: {warning_msg}",
                confidence=0.0,
                is_conversational=True,
                clear_pending=False,
            )

    def _dispatch_calendar_action(
        self,
        plan: CognitivePlan,
        question: Question,
        context: ConversationContext | None,
    ) -> Answer:
        """
        Execute calendar mutations produced by CognitivePlanner with domain safeguards.
        Prioritizes structured execution via CalendarAgent, falling back to handle_message()
        when parameters are not sufficiently structured.
        """
        if self._calendar_agent is None:
            return Answer(
                text="⚠️ Calendar service is currently unavailable.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        # 1. Resolve authenticated requester identity
        user_id = ""
        if context and context.user_id:
            user_id = str(context.user_id).strip()
        elif question.target_user_id:
            user_id = str(question.target_user_id).strip()

        channel_id = str(context.channel_id).strip() if context and context.channel_id else ""

        # 2. Extract step parameters and action
        cal_step = next(
            (step for step in plan.execution_steps if step.agent == TargetAgent.CALENDAR_AGENT),
            plan.execution_steps[0] if plan.execution_steps else None,
        )
        step_params = dict(cal_step.parameters) if cal_step else {}
        action_type = cal_step.action_type if cal_step else ActionType.CREATE
        action_name = cal_step.action if cal_step else "create_event"

        # Merge extracted entities into parameters if missing
        merged_params = dict(step_params)
        if plan.entities:
            if not merged_params.get("title") and plan.entities.event_title:
                merged_params["title"] = plan.entities.event_title
            if not merged_params.get("dates") and plan.entities.dates:
                merged_params["dates"] = plan.entities.dates
            if not merged_params.get("times") and plan.entities.times:
                merged_params["times"] = plan.entities.times
            if not merged_params.get("duration_minutes") and plan.entities.duration_minutes is not None:
                merged_params["duration_minutes"] = plan.entities.duration_minutes
            if not merged_params.get("audience_type") and plan.entities.audience_type:
                merged_params["audience_type"] = plan.entities.audience_type
            if not merged_params.get("audience_identifier") and not merged_params.get("audience_id"):
                if plan.entities.audience_id:
                    merged_params["audience_identifier"] = plan.entities.audience_id
                elif plan.entities.team_names:
                    merged_params["audience_identifier"] = plan.entities.team_names[0]
                    if not merged_params.get("audience_type"):
                        merged_params["audience_type"] = "team"
                elif plan.entities.employee_names:
                    merged_params["audience_identifier"] = plan.entities.employee_names[0]
                    if not merged_params.get("audience_type"):
                        merged_params["audience_type"] = "individual"
            if not merged_params.get("entry_id") and plan.entities.item_reference:
                merged_params["entry_id"] = plan.entities.item_reference

        # Determine operation category
        is_cancel = action_type == ActionType.CANCEL or any(w in action_name.lower() for w in ("cancel", "delete", "remove"))
        is_update = action_type == ActionType.UPDATE or any(w in action_name.lower() for w in ("update", "reschedule", "modify"))
        is_create = not is_cancel and not is_update

        # Determine if structured parameters are sufficient
        entry_id_val = merged_params.get("entry_id") or merged_params.get("item_reference")
        has_sufficient_structured = False

        if is_cancel or is_update:
            has_sufficient_structured = bool(user_id) and bool(entry_id_val and str(entry_id_val).strip())
        elif is_create:
            has_title = bool(merged_params.get("title") or merged_params.get("event_title") or merged_params.get("summary"))
            has_time = bool(
                merged_params.get("start_time")
                or (merged_params.get("dates") and merged_params.get("times"))
                or (merged_params.get("date") and merged_params.get("time"))
            )
            has_aud = bool(
                merged_params.get("audience_type")
                and (
                    merged_params.get("audience_identifier")
                    or merged_params.get("audience_id")
                    or str(merged_params.get("audience_type")).lower() == "organization"
                )
            )
            has_sufficient_structured = bool(user_id) and has_title and has_time and has_aud

        # PRIORITY 1: Structured Execution
        if has_sufficient_structured and hasattr(self._calendar_agent, "execute_structured"):
            action_verb = "cancel" if is_cancel else ("update" if is_update else "create")
            try:
                result = self._calendar_agent.execute_structured(
                    action_verb,
                    merged_params,
                    user_id=user_id,
                )
                if isinstance(result, str):
                    return Answer(
                        text=result,
                        confidence=1.0,
                        is_conversational=True,
                        clear_pending=True,
                    )
            except UnauthorizedCalendarActionError:
                return Answer(
                    text="I can't perform this calendar action because you are not authorized. Only the creator can modify or cancel it.",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )
            except (InvalidCalendarEntryError, InvalidTimeRangeError, InvalidAudienceError, CalendarEntryNotFoundError) as err:
                return Answer(
                    text=f"⚠️ I couldn't execute the calendar action: {err}",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )
            except CalendarDomainError as err:
                return Answer(
                    text=f"⚠️ Calendar action failed: {err}",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )
            except Exception as err:
                logger.exception("Unexpected error during structured calendar execution: %s", err)
                return Answer(
                    text="⚠️ I ran into an error while processing the calendar entry. Please try again.",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

        # PRIORITY 2: Natural-Language Fallback (handle_message)
        # Retain handle_message() for requests that are not sufficiently structured
        cal_resp: str | None = None
        if hasattr(self._calendar_agent, "handle_message"):
            cal_resp = self._calendar_agent.handle_message(
                question.text,
                user_id=user_id,
                channel_id=channel_id,
            )
            if cal_resp is None and plan.execution_steps:
                dates_str = merged_params.get("dates", ["tomorrow"])[0] if merged_params.get("dates") else "tomorrow"
                times_str = merged_params.get("times", ["9am"])[0] if merged_params.get("times") else "9am"
                title_str = merged_params.get("title") or "Meeting"
                reconstructed = f"Schedule {title_str} on {dates_str} at {times_str}"
                cal_resp = self._calendar_agent.handle_message(
                    reconstructed,
                    user_id=user_id,
                    channel_id=channel_id,
                )

        if cal_resp is not None:
            # Check if confirmation or clarification/rejection
            is_confirmed = any(
                phrase in cal_resp.lower()
                for phrase in (
                    "done!",
                    "successfully scheduled",
                    "successfully rescheduled",
                    "successfully cancelled",
                    "added it to the calendar",
                    "updated the calendar",
                    "cancelled it",
                )
            )
            return Answer(
                text=cal_resp,
                confidence=1.0,
                is_conversational=True,
                clear_pending=is_confirmed,
            )

        # PRIORITY 3: Explicit failure / clarification (Never silently fall through)
        if not user_id:
            return Answer(
                text="⚠️ Requester identity is required to perform calendar actions.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        if (is_cancel or is_update) and not entry_id_val:
            action_desc = "cancel" if is_cancel else "update"
            return Answer(
                text=f"⚠️ Cannot {action_desc} calendar entry: entry ID is required.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        return Answer(
            text=(
                "⚠️ I understood you wanted to perform a calendar action, but I need more details to complete it. "
                "Please provide the title, date, time, and intended audience (or entry ID for updates/cancellations)."
            ),
            confidence=1.0,
            is_conversational=True,
            clear_pending=False,
        )

    def _dispatch_reminder_action(
        self,
        plan: CognitivePlan,
        question: Question,
        context: ConversationContext | None,
    ) -> Answer:
        """
        Execute reminder mutations produced by CognitivePlanner with domain safeguards.
        Only supported for daily recurring task check-in reminders linked to an existing
        open operational task via OperationsAgent.
        """
        # 1. Check reminder service availability
        if self._operations_agent is None or getattr(self._operations_agent, "reminder_service", None) is None:
            return Answer(
                text="⚠️ Reminder service is currently unavailable.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        # 2. Authenticated requester identity
        user_id = ""
        if context and context.user_id:
            user_id = str(context.user_id).strip()
        elif question.target_user_id:
            user_id = str(question.target_user_id).strip()

        if not user_id:
            return Answer(
                text="⚠️ Requester identity is required to perform reminder actions.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        # 3. Extract step parameters and fallback to plan entities
        rem_step = next(
            (
                s for s in plan.execution_steps
                if s.agent in (TargetAgent.REMINDER_SERVICE, TargetAgent.OPERATIONS_AGENT)
            ),
            plan.execution_steps[0] if plan.execution_steps else None,
        )
        step_params = dict(rem_step.parameters) if rem_step else {}

        if plan.entities:
            if not step_params.get("task_id") and not step_params.get("item_reference"):
                if plan.entities.item_reference:
                    step_params["task_id"] = plan.entities.item_reference
            if not step_params.get("target_user_id") and not step_params.get("assignee"):
                if plan.entities.target_user_id:
                    step_params["target_user_id"] = plan.entities.target_user_id
                elif plan.entities.employee_names:
                    step_params["target_user_id"] = plan.entities.employee_names[0]
            if not step_params.get("times") and plan.entities.times:
                step_params["times"] = plan.entities.times

        # 4. Check for unsupported one-time reminder / timer requests
        raw_text = question.text.lower() if question.text else ""
        is_one_time = (
            step_params.get("one_time") is True
            or step_params.get("timer") is True
            or str(step_params.get("type", "")).lower() in ("one_time", "timer", "once", "single")
            or "duration_minutes" in step_params
            or bool(
                re.search(
                    r"\b(?:in\s+\d+\s*(?:mins?|minutes?|hours?|secs?|seconds?)|set\s+(?:a\s+)?timer|timer\s+for|one[- ]time\s+reminder|remind\s+me\s+once)\b",
                    raw_text,
                )
            )
        )
        if is_one_time:
            return Answer(
                text=(
                    "⚠️ POLIS currently only supports daily recurring task check-in reminders "
                    "(configured with two daily check-in times) linked to an existing operational task. "
                    "One-time reminders and generic timers are not currently supported."
                ),
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        # 5. Validate Task ID
        task_id = str(step_params.get("task_id") or step_params.get("item_reference") or "").strip()
        if not task_id:
            return Answer(
                text="⚠️ Cannot schedule task reminder: a valid task ID is required.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        task = self._operations_agent.get_task(task_id)
        if task is None:
            return Answer(
                text=f"⚠️ Cannot schedule task reminder: task '{task_id}' was not found.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        if task.status in (
            OperationalItemStatus.COMPLETED,
            OperationalItemStatus.CANCELLED,
            OperationalItemStatus.CLOSED,
        ):
            return Answer(
                text=(
                    f"⚠️ Cannot schedule reminder for task '{task_id}' because it is in status '{task.status.value}'. "
                    "Reminders can only be scheduled for open tasks."
                ),
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        # 6. Validate Target User
        target_user_id = str(step_params.get("target_user_id") or step_params.get("assignee") or "").strip()
        if not target_user_id and task.owner_id and str(task.owner_id).strip():
            target_user_id = str(task.owner_id).strip()

        if not target_user_id:
            return Answer(
                text="⚠️ Cannot schedule task reminder: target user is required.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        # 7. Validate Channel Context
        channel_id = str(
            step_params.get("channel_id")
            or (context.channel_id if context and context.channel_id else "")
        ).strip()
        if not channel_id:
            return Answer(
                text="⚠️ Cannot schedule task reminder: Slack channel context is required.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        # 8. Validate Source Message Timestamp
        source_message_ts = str(
            step_params.get("source_message_ts")
            or step_params.get("message_ts")
            or (context.thread_ts if context and context.thread_ts else "")
        ).strip()
        if not source_message_ts:
            return Answer(
                text="⚠️ Cannot schedule task reminder: source message timestamp is required.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )
        source_thread_ts = (
            str(step_params.get("source_thread_ts") or (context.thread_ts if context and context.thread_ts else "")).strip()
            or None
        )

        # 9. Validate Reminder Times
        raw_times = step_params.get("times")
        time_1 = step_params.get("time_1")
        time_2 = step_params.get("time_2")

        if isinstance(raw_times, list) and raw_times:
            if not time_1 and len(raw_times) >= 1:
                time_1 = str(raw_times[0]).strip()
            if not time_2 and len(raw_times) >= 2:
                time_2 = str(raw_times[1]).strip()

        if not time_1:
            return Answer(
                text="⚠️ Cannot schedule task reminder: reminder times are required (e.g., '09:00' and '17:00').",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        if not time_2:
            time_2 = "17:00"

        time_1_str = str(time_1).strip()
        time_2_str = str(time_2).strip()
        try:
            time.fromisoformat(time_1_str)
            time.fromisoformat(time_2_str)
        except (ValueError, TypeError):
            return Answer(
                text=f"⚠️ Cannot schedule task reminder: invalid reminder time format '{time_1}' / '{time_2}'. Times must be HH:MM in 24-hour format (e.g., '09:00').",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        # 10. Validate Timezone
        timezone_name = str(step_params.get("timezone_name") or step_params.get("timezone") or "UTC").strip()
        try:
            ZoneInfo(timezone_name)
        except Exception:
            return Answer(
                text=f"⚠️ Cannot schedule task reminder: invalid timezone '{timezone_name}'.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        # 11. Duplicate / Idempotent Scheduling Check
        existing_reminder = self._operations_agent.find_active_task_reminder(task_id, target_user_id)
        if existing_reminder is not None:
            return Answer(
                text=(
                    f"A daily check-in reminder is already active for task '{task.summary}' "
                    f"(Target: `{target_user_id}`). Existing reminder is scheduled for daily check-in. "
                    "No duplicate reminder was created."
                ),
                confidence=1.0,
                is_conversational=True,
                clear_pending=True,
            )

        # 12. Execute scheduling via OperationsAgent
        try:
            reminder = self._operations_agent.schedule_task_reminder(
                task_id=task_id,
                target_user_id=target_user_id,
                creator_user_id=user_id,
                channel_id=channel_id,
                source_message_ts=source_message_ts,
                source_thread_ts=source_thread_ts,
                timezone_name=timezone_name,
                time_1=time_1_str,
                time_2=time_2_str,
            )
            if reminder is not None:
                return Answer(
                    text=(
                        f"Done! I've scheduled daily reminders for task *{task.summary}* (`{task_id}`).\n\n"
                        f"✅ Successfully scheduled task reminder:\n"
                        f"• *Task:* {task.summary}\n"
                        f"• *Target User:* `{target_user_id}`\n"
                        f"• *Creator:* `{user_id}`\n"
                        f"• *Daily Check-in Times:* {time_1_str} and {time_2_str} ({timezone_name})\n"
                        f"• *Channel:* `{channel_id}`"
                    ),
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=True,
                )
            else:
                return Answer(
                    text="⚠️ Reminder service is currently unavailable.",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )
        except OperationalItemNotFoundError as err:
            return Answer(
                text=f"⚠️ Cannot schedule task reminder: {err}",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )
        except (InvalidLifecycleTransitionError, OperationalError) as err:
            return Answer(
                text=f"⚠️ Cannot schedule task reminder: {err}",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )
        except Exception as err:
            logger.exception("Unexpected error scheduling task reminder: %s", err)
            return Answer(
                text=f"⚠️ Reminder scheduling failed: {err}",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

    def _dispatch_governance_action(
        self,
        plan: CognitivePlan,
        question: Question,
        context: ConversationContext | None,
    ) -> Answer:
        """
        Execute a structured governance action via GovernanceAgent.

        Supported operations:
        - CREATE: request_approval (requires title, target_object, authenticated requester identity).
        - UPDATE: grant_approval, reject_approval (strictly requires verified approver authorization,
          valid approval ID, and rejection reason for reject).
        - Unsupported mutations (policy mutations, unverified grant/reject) are safely rejected
          with clear explanatory answers, preserving pending state where appropriate.
        """
        # 1. Verify GovernanceAgent availability
        if self._governance_agent is None or not getattr(self._governance_agent, "enabled", True):
            return Answer(
                text="⚠️ Governance Agent is not available or disabled by configuration.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        # 2. Extract primary governance execution step
        gov_step = next(
            (
                s for s in plan.execution_steps
                if s.agent == TargetAgent.GOVERNANCE_AGENT
                or s.action_type in (ActionType.CREATE, ActionType.UPDATE)
                or any(k in s.action.lower() for k in ("approval", "grant", "reject", "policy"))
            ),
            plan.execution_steps[0] if plan.execution_steps else None,
        )
        if gov_step is None:
            return Answer(
                text="⚠️ Cannot execute governance action: no execution step provided.",
                confidence=1.0,
                is_conversational=True,
                clear_pending=False,
            )

        step_params = dict(gov_step.parameters or {})
        action_name = gov_step.action.lower().strip()
        action_type = gov_step.action_type

        # Merge extracted entities from plan into parameters as fallback only
        if plan.entities:
            if not step_params.get("title") and (plan.entities.task_summary or plan.entities.event_title):
                step_params["title"] = plan.entities.task_summary or plan.entities.event_title
            if not step_params.get("target_object") and plan.entities.item_reference:
                step_params["target_object"] = plan.entities.item_reference
            if not step_params.get("approval_id") and plan.entities.item_reference:
                step_params["approval_id"] = plan.entities.item_reference
            if plan.entities.extra_params:
                for k, v in plan.entities.extra_params.items():
                    if k not in step_params and v:
                        step_params[k] = v

        # Determine operation category
        is_request = (
            action_type == ActionType.CREATE
            or any(w in action_name for w in ("request", "create", "submit", "ask"))
        )
        is_reject = (
            not is_request
            and any(w in action_name for w in ("reject", "deny"))
        )
        is_grant = (
            not is_request
            and not is_reject
            and (any(w in action_name for w in ("grant", "approve")) or action_type == ActionType.UPDATE)
        )

        # ---------------------------------------------------------------------
        # OPERATION 1: REQUEST APPROVAL (CREATE)
        # ---------------------------------------------------------------------
        if is_request:
            # 1. Authenticated requester identity (Context MUST NOT be overridden by planner)
            requester_id = (
                (context.user_id if context and context.user_id else "")
                or (question.target_user_id if question and question.target_user_id else "")
            ).strip()

            if not requester_id:
                return Answer(
                    text="⚠️ Cannot request approval: requester identity cannot be verified from the authenticated conversation context.",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

            # 2. Validate title
            title = str(step_params.get("title") or step_params.get("summary") or "").strip()
            if not title:
                return Answer(
                    text="⚠️ Cannot request approval: a valid approval title is required.",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

            # 3. Validate target_object
            target_object = str(
                step_params.get("target_object")
                or step_params.get("affected_object")
                or step_params.get("target")
                or step_params.get("resource")
                or ""
            ).strip()
            if not target_object:
                return Answer(
                    text="⚠️ Cannot request approval: a valid target object or resource is required.",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

            # 4. Validate optional policy_id if provided
            raw_policy_id = step_params.get("policy_id")
            policy_id_val: str | None = None
            if raw_policy_id and str(raw_policy_id).strip():
                policy_id_val = str(raw_policy_id).strip()
                policy = self._governance_agent.get_policy(policy_id_val)
                if policy is None:
                    return Answer(
                        text=f"⚠️ Cannot request approval: policy '{policy_id_val}' was not found.",
                        confidence=1.0,
                        is_conversational=True,
                        clear_pending=False,
                    )

            correlation_id_val = str(step_params.get("correlation_id", "")).strip() or None
            notes_val = str(step_params.get("notes", "")).strip()

            try:
                approval = self._governance_agent.request_approval(
                    title=title,
                    target_object=target_object,
                    requester_id=requester_id,
                    policy_id=policy_id_val,
                    correlation_id=correlation_id_val,
                    notes=notes_val,
                )
                response_lines = [
                    "✅ Approval request submitted successfully.",
                    f"• ID: {approval.id}",
                    f"• Title: {approval.title}",
                    f"• Target Object: {approval.target_object}",
                    f"• Status: {approval.status.value}",
                    f"• Requester: {approval.requester_id}",
                ]
                if approval.policy_id:
                    response_lines.append(f"• Policy ID: {approval.policy_id}")
                if approval.notes:
                    response_lines.append(f"• Notes: {approval.notes}")

                return Answer(
                    text="\n".join(response_lines),
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=True,
                )
            except Exception as e:
                logger.error("Governance request_approval failed: %s", e, exc_info=True)
                return Answer(
                    text=f"⚠️ Failed to create approval request: {e}",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

        # ---------------------------------------------------------------------
        # OPERATION 2 & 3: GRANT OR REJECT APPROVAL (UPDATE)
        # ---------------------------------------------------------------------
        if is_grant or is_reject:
            op_label = "grant" if is_grant else "reject"

            # 1. Authoritative approver identity (Context MUST NOT be overridden by planner)
            approver_id = (
                (context.user_id if context and context.user_id else "")
                or (question.target_user_id if question and question.target_user_id else "")
            ).strip()

            if not approver_id:
                return Answer(
                    text=f"⚠️ Cannot {op_label} approval: approver identity cannot be verified from the authenticated conversation context.",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

            # 2. Validate approval ID
            approval_id = str(
                step_params.get("approval_id")
                or step_params.get("request_id")
                or step_params.get("item_reference")
                or ""
            ).strip()
            if not approval_id:
                return Answer(
                    text=f"⚠️ Cannot {op_label} approval: a valid approval ID is required.",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

            # 3. For rejection, validate reason
            rejection_reason = ""
            if is_reject:
                rejection_reason = str(step_params.get("reason") or step_params.get("notes") or "").strip()
                if not rejection_reason:
                    return Answer(
                        text="⚠️ Cannot reject approval: a meaningful rejection reason is required.",
                        confidence=1.0,
                        is_conversational=True,
                        clear_pending=False,
                    )

            # 4. Verify Approval Existence
            approval = self._governance_agent.find_approval(approval_id)
            if approval is None:
                return Answer(
                    text=f"⚠️ Cannot {op_label} approval: approval request '{approval_id}' was not found.",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

            # 5. Authorization Verification
            # If the application does not expose an approver authorization path, safely reject
            if not self._governance_agent.has_approver_authorization_path():
                return Answer(
                    text=(
                        f"⚠️ Cannot {op_label} approval: POLIS does not expose an approver authorization mechanism "
                        f"in this conversational channel. Approvals must be granted or rejected through an authorized "
                        f"governance portal or verified organizational event."
                    ),
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

            # Verify that current approver is authorized
            if not self._governance_agent.is_authorized_approver(approver_id, approval):
                return Answer(
                    text=f"⚠️ Unauthorized: user '{approver_id}' is not authorized to {op_label} approval request '{approval.id}'.",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

            # 6. Validate Lifecycle Transition
            target_status = ApprovalStatus.GRANTED if is_grant else ApprovalStatus.REJECTED
            try:
                self._governance_agent.validate_approval_transition(approval.status, target_status)
            except InvalidApprovalTransitionError as e:
                return Answer(
                    text=f"⚠️ Cannot {op_label} approval '{approval.id}': {e}",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

            # 7. Execute Grant or Reject
            notes_val = str(step_params.get("notes", "")).strip()
            try:
                if is_grant:
                    updated = self._governance_agent.grant_approval(
                        approval_id=approval.id,
                        approver_id=approver_id,
                        notes=notes_val,
                    )
                    action_past = "granted"
                else:
                    updated = self._governance_agent.reject_approval(
                        approval_id=approval.id,
                        approver_id=approver_id,
                        reason=rejection_reason,
                    )
                    action_past = "rejected"

                response_lines = [
                    f"✅ Approval request {action_past} successfully.",
                    f"• ID: {updated.id}",
                    f"• Title: {updated.title}",
                    f"• Status: {updated.status.value}",
                    f"• Approver: {updated.approver_id}",
                ]
                if updated.granted_at:
                    response_lines.append(f"• Granted At: {updated.granted_at.isoformat()}")
                if updated.notes:
                    response_lines.append(f"• Notes: {updated.notes}")

                return Answer(
                    text="\n".join(response_lines),
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=True,
                )
            except Exception as e:
                logger.error("Governance %s_approval failed: %s", op_label, e, exc_info=True)
                return Answer(
                    text=f"⚠️ Failed to {op_label} approval request '{approval.id}': {e}",
                    confidence=1.0,
                    is_conversational=True,
                    clear_pending=False,
                )

        # ---------------------------------------------------------------------
        # OPERATION 4: UNSUPPORTED GOVERNANCE MUTATION
        # ---------------------------------------------------------------------
        return Answer(
            text=f"⚠️ Governance operation '{action_name}' is not supported. POLIS only supports requesting, granting, or rejecting approvals.",
            confidence=1.0,
            is_conversational=True,
            clear_pending=False,
        )

    # =========================================================================
    # PERSONALIZED MORNING GREETING & TASK BRIEFING
    # =========================================================================

    @staticmethod
    def _is_greeting_message(question: Question) -> bool:
        """
        Determine if the user query is a natural greeting eligible for a morning briefing.
        Explicitly excludes ordinary farewells, sign-offs, thanks, or substantive questions.
        """
        raw_text = getattr(question, "text", "") or ""
        text = raw_text.strip()
        if not text:
            return False

        norm = " ".join(text.lower().split()).rstrip(".!?")
        norm = re.sub(r"^<@[a-z0-9_|-]+>\s*[,:]?\s*", "", norm)
        norm = re.sub(r"^@polis\s*[,:]?\s*", "", norm)
        norm = norm.strip(" :,;—–-")

        # Explicitly exclude farewells
        farewell_patterns = (
            r"\b(?:bye|goodbye|good\s+bye|see\s+ya|see\s+you|talk\s+later|good\s*night|goodnight)\b",
            r"\b(?:have\s+a\s+(?:good|nice)\s+(?:day|evening|weekend|one))\b",
        )
        if any(re.search(pat, norm) for pat in farewell_patterns):
            return False

        # Explicitly exclude sign-offs
        signoff_patterns = (
            r"\b(?:signing|logging)\s+off\b",
            r"\b(?:done|finished)\s+for\s+(?:today|the\s+day)\b",
            r"\b(?:ending|stopping)\s+work\b",
            r"\b(?:leaving\s+work|logging\s+out)\b",
        )
        if any(re.search(pat, norm) for pat in signoff_patterns):
            return False

        # Explicitly exclude thanks or identity questions
        if norm.startswith("thank") or norm.startswith("thx") or norm in ("who are you", "what is polis"):
            return False

        # Natural greeting regex (anchored to entire message, allowing addressing polis/team/there)
        greeting_pattern = (
            r"^(?:good\s+(?:morning|afternoon|evening|day)|morning|afternoon|evening|hi|hello|hey|hiya|howdy)"
            r"(?:[\s,]+(?:polis|there|team|everyone|all|folks|<@[a-z0-9_|-]+>|@[a-z0-9_.-]+))?$"
        )
        return bool(re.match(greeting_pattern, norm))

    def _get_operational_repository(self) -> OperationalItemRepository | None:
        if self._operational_item_repository is not None:
            return self._operational_item_repository
        if self._operations_agent is not None:
            repo = getattr(self._operations_agent, "_repository", None)
            if repo is not None:
                return repo
        if self._operational_item_service is not None:
            repo = getattr(self._operational_item_service, "_repository", None)
            if repo is not None:
                return repo
        return None

    @staticmethod
    def _is_public_channel(ctx: ConversationContext | None) -> bool:
        if ctx is None:
            return False
        # Direct Messages (im) are always private
        if getattr(ctx, "channel_type", None) == "im":
            return False
        cid = getattr(ctx, "channel_id", "") or ""
        if cid.startswith("D"):
            return False
        # Threads addressed to POLIS are private conversational threads
        if getattr(ctx, "is_thread", False) is True:
            return False
        # Top-level public channel messages must not disclose private tasks
        if getattr(ctx, "channel_type", None) in ("channel", "public_channel", "group") or cid.startswith("C"):
            return True
        return False

    @staticmethod
    def _is_raw_user_id(val: str) -> bool:
        if not val:
            return True
        trimmed = val.strip()
        return bool(re.match(r"^[UW][A-Z0-9_-]{5,}$", trimmed) or re.match(r"^U_[A-Z0-9_-]+$", trimmed))

    def _resolve_sender_display_name(
        self,
        question: Question,
        ctx: ConversationContext | None,
        sender_id: str,
    ) -> str:
        # 1. From question.user_name if human readable
        q_user = getattr(question, "user_name", None)
        if q_user and not self._is_raw_user_id(q_user):
            return q_user.strip()

        # 2. From question.target_user_name if human readable
        q_name = getattr(question, "target_user_name", None)
        if q_name and not self._is_raw_user_id(q_name):
            return q_name.strip()

        # 3. From identity resolver if configured
        resolver = self._identity_resolver or getattr(self._calendar_agent, "_identity_resolver", None)
        if resolver is not None and sender_id:
            if hasattr(resolver, "get_display_name"):
                try:
                    name = resolver.get_display_name(sender_id)
                    if name and not self._is_raw_user_id(name):
                        return name.strip()
                except Exception:
                    pass
            if hasattr(resolver, "get_workspace_users"):
                try:
                    users = resolver.get_workspace_users()
                    for u in users:
                        if u.get("id") == sender_id:
                            name = (
                                u.get("profile", {}).get("display_name")
                                or u.get("real_name")
                                or u.get("name")
                                or ""
                            )
                            if name and not self._is_raw_user_id(name):
                                return name.strip()
                            break
                except Exception:
                    pass

        return ""

    @staticmethod
    def _build_salutation(display_name: str, query_text: str) -> str:
        norm = (query_text or "").lower()
        if "afternoon" in norm:
            prefix = "Good afternoon"
        elif "evening" in norm:
            prefix = "Good evening"
        elif re.search(r"\b(?:hi|hey)\b", norm):
            prefix = "Hi"
        elif "hello" in norm:
            prefix = "Hello"
        else:
            prefix = "Good morning"

        if display_name:
            return f"{prefix}, {display_name}! 👋"
        return f"{prefix}! 👋"

    def _handle_morning_briefing(
        self,
        question: Question,
        context: ConversationContext | None = None,
    ) -> Answer | None:
        """
        Produce a personalized morning greeting and open task briefing for the sender.
        Returns None if no repository or sender identity is available.
        """
        ctx = context or getattr(question, "context", None)
        sender_id = (
            (getattr(ctx, "user_id", None) if ctx else None)
            or getattr(question, "user_id", None)
            or getattr(question, "target_user_id", None)
            or ""
        )

        repo = self._get_operational_repository()
        if repo is None or not sender_id:
            return None

        display_name = self._resolve_sender_display_name(question, ctx, sender_id)
        salutation = self._build_salutation(display_name, question.text)

        # Check public channel privacy: do not expose private tasks in public channels
        if self._is_public_channel(ctx):
            return Answer(text=salutation, is_conversational=True)

        try:
            query_owner_ids: set[str] = {sender_id}
            resolver = self._identity_resolver or getattr(self._calendar_agent, "_identity_resolver", None)
            if resolver and hasattr(resolver, "get_all_identifiers_for_user"):
                query_owner_ids.update(resolver.get_all_identifiers_for_user(sender_id))

            open_tasks = repo.find_open_for_owner_or_name(
                owner_id=list(query_owner_ids) if len(query_owner_ids) > 1 else sender_id,
                owner_name=display_name or "",
                item_type=OperationalItemType.TASK,
            )
        except Exception as exc:
            logger.exception("Failed to retrieve open tasks for sender %s: %s", sender_id, exc)
            return Answer(
                text=(
                    f"{salutation}\n\n"
                    "I was unable to retrieve your morning task briefing right now. Please try again in a moment."
                ),
                is_conversational=True,
            )

        org_notices: list[str] = []
        try:
            open_decisions = repo.find_open(item_type=OperationalItemType.DECISION)
            for dec in open_decisions[:2]:
                org_notices.append(f"• Decision: {dec.summary}")
            open_risks = repo.find_open(item_type=OperationalItemType.RISK)
            for rsk in open_risks[:2]:
                org_notices.append(f"• Note: {rsk.summary}")
        except Exception:
            pass

        if not open_tasks:
            empty_sections = [
                salutation,
                "You currently have no open tasks recorded.\n\nLet me know if there's anything else you'd like to work on today!",
            ]
            if org_notices:
                empty_sections.append("📢 Organization Context:\n" + "\n".join(org_notices))
            return Answer(
                text="\n\n".join(empty_sections),
                is_conversational=True,
            )

        now = datetime.now(timezone.utc)
        overdue_tasks: list[OperationalItem] = []
        due_soon_tasks: list[OperationalItem] = []

        task_lines: list[str] = []
        for idx, task in enumerate(open_tasks, start=1):
            status_label = "In Progress" if task.status == OperationalItemStatus.IN_PROGRESS else "Open"
            line_parts = [f"{idx}. {task.summary} — {status_label}"]

            if task.due_at is not None:
                t_due = task.due_at
                if t_due.tzinfo is None:
                    t_due = t_due.replace(tzinfo=timezone.utc)
                due_fmt = t_due.strftime("%Y-%m-%d")

                if t_due < now:
                    overdue_tasks.append(task)
                    line_parts.append(f"Due: {due_fmt} [Overdue]")
                elif t_due <= now + timedelta(days=1):
                    due_soon_tasks.append(task)
                    line_parts.append(f"Due: {due_fmt} [Due soon]")
                else:
                    line_parts.append(f"Due: {due_fmt}")

            task_lines.append(" — ".join(line_parts))

        count = len(open_tasks)
        count_header = f"You currently have {count} open task{'s' if count != 1 else ''}:"

        highlights: list[str] = []
        if overdue_tasks:
            overdue_titles = ", ".join(f"'{t.summary}'" for t in overdue_tasks)
            highlights.append(
                f"⚠️ You have {len(overdue_tasks)} overdue task{'s' if len(overdue_tasks) != 1 else ''}: {overdue_titles}."
            )
        elif due_soon_tasks:
            due_titles = ", ".join(f"'{t.summary}'" for t in due_soon_tasks)
            highlights.append(
                f"⏰ Due soon: {due_titles}."
            )

        # Grounded starting recommendation
        recommended_task = None
        reason = ""

        if overdue_tasks:
            recommended_task = overdue_tasks[0]
            t_due = recommended_task.due_at
            if t_due.tzinfo is None:
                t_due = t_due.replace(tzinfo=timezone.utc)
            reason = f"it is overdue (due {t_due.strftime('%Y-%m-%d')})"
        elif due_soon_tasks:
            recommended_task = due_soon_tasks[0]
            t_due = recommended_task.due_at
            if t_due.tzinfo is None:
                t_due = t_due.replace(tzinfo=timezone.utc)
            reason = f"it is due soon on {t_due.strftime('%Y-%m-%d')}"
        else:
            in_progress = [t for t in open_tasks if t.status == OperationalItemStatus.IN_PROGRESS]
            if in_progress:
                recommended_task = in_progress[0]
                reason = "it is already in progress"
            else:
                high_pri = [
                    t for t in open_tasks
                    if t.priority in (OperationalItemPriority.CRITICAL, OperationalItemPriority.HIGH)
                ]
                if high_pri:
                    recommended_task = high_pri[0]
                    reason = f"it has {recommended_task.priority.value} priority"
                else:
                    recommended_task = open_tasks[0]
                    reason = "it is your next scheduled open task"

        recommendation_block = (
            f"I recommend starting with '{recommended_task.summary}' because {reason}.\n\n"
            "Would you like me to help you break it down into the first actionable steps? Would you like me to help you get started?"
        )

        sections = [
            salutation,
            count_header,
            "\n".join(task_lines),
        ]
        if highlights:
            sections.append("\n".join(highlights))
        sections.append(recommendation_block)
        if org_notices:
            sections.append("📢 Organization Context:\n" + "\n".join(org_notices))

        return Answer(
            text="\n\n".join(sections),
            is_conversational=True,
        )

    def _handle_employee_work_query(
        self,
        question: Question,
        context: ConversationContext | None,
        plan: CognitivePlan,
    ) -> Answer:
        """
        Handle person-specific recent work and task retrieval via PersonWorkService.
        """
        if self._person_work_service is None:
            logger.warning("PersonWorkService not configured on SimpleCognitiveEngine.")
            return Answer(
                text="Person-specific work retrieval is not currently configured.",
                confidence=0.5,
                is_conversational=True,
            )

        step_params = plan.execution_steps[0].parameters if plan.execution_steps else {}
        target_user_id = (
            plan.entities.target_user_id
            or question.target_user_id
            or step_params.get("target_user_id")
        )
        target_user_name = (
            plan.entities.target_user_name
            or question.target_user_name
            or step_params.get("target_user_name")
        )
        req_user_id = (
            question.user_id
            or (context.user_id if context else None)
            or getattr(question, "requester_user_id", None)
            or step_params.get("requester_user_id")
        )

        norm_q = question.text.lower()
        is_self = bool(
            re.search(r"\b(?:what\s+am\s+i|have\s+i|my\s+work|my\s+tasks|my\s+priorities|should\s+i\s+work|my\s+recent\s+work)\b", norm_q)
            or (not target_user_id and not target_user_name and req_user_id)
        )

        if is_self and req_user_id:
            target_user_id = req_user_id
            if not target_user_name and self._identity_resolver is not None:
                try:
                    if hasattr(self._identity_resolver, "get_display_name"):
                        target_user_name = self._identity_resolver.get_display_name(req_user_id)
                except Exception:
                    pass

        # If name is present but id is not, try identity resolver to disambiguate or resolve id
        if not target_user_id and target_user_name and self._identity_resolver is not None:
            try:
                users = []
                if hasattr(self._identity_resolver, "get_workspace_users"):
                    users = self._identity_resolver.get_workspace_users()
                matches = []
                for u in users:
                    disp = u.get("profile", {}).get("display_name") or ""
                    real = u.get("real_name") or ""
                    uname = u.get("name") or ""
                    candidates = {disp.lower(), real.lower(), uname.lower()}
                    if any(target_user_name.lower() == c or target_user_name.lower() in c.split() for c in candidates if c):
                        matches.append(u)

                if len(matches) > 1:
                    candidate_names = [
                        (u.get("profile", {}).get("display_name") or u.get("real_name") or u.get("name") or u["id"])
                        for u in matches
                    ]
                    cand_str = ", ".join(f"`{c}`" for c in candidate_names)
                    return Answer(
                        text=f"Multiple team members match that name ({cand_str}). Could you please clarify which person you mean?",
                        confidence=1.0,
                        is_conversational=True,
                    )
                elif len(matches) == 1:
                    target_user_id = matches[0]["id"]
                    target_user_name = (
                        matches[0].get("profile", {}).get("display_name")
                        or matches[0].get("real_name")
                        or matches[0].get("name")
                    )
            except Exception as e:
                logger.warning("Identity resolution error in _handle_employee_work_query: %s", e)

        # Lookback period: default 7 days, 30 days if specified
        lookback_days = 7
        if "30 days" in norm_q or "month" in norm_q or "past month" in norm_q:
            lookback_days = 30

        # Wire LLM client to PersonWorkService if not already configured
        if getattr(self._person_work_service, "llm_client", None) is None:
            engine_llm = (
                getattr(self._planner, "_llm_client", None)
                or getattr(self._question_answering, "_llm_client", None)
            )
            if engine_llm is not None:
                self._person_work_service.llm_client = engine_llm

        summary = self._person_work_service.get_person_work_summary(
            target_user_id=target_user_id,
            target_user_name=target_user_name,
            requester_user_id=req_user_id,
            query_text=question.text,
            lookback_days=lookback_days,
            is_self=is_self,
        )

        clear_pending = bool(context and context.pending_operation)
        return Answer(
            text=summary.formatted_response,
            confidence=1.0,
            evidence=[item.text if hasattr(item, "text") else item.evidence for item in summary.items],
            is_conversational=True,
            clear_pending=clear_pending,
        )
