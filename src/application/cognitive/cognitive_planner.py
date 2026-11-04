"""
Centralized Cognitive Planner for POLIS.

Interprets employee requests, extracts entities and parameters, identifies missing
information, handles pending-operation continuations and cancellations, and produces
validated, structured CognitivePlan objects for selective specialist execution.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from domain.reasoning.value_objects.conversation_context import ConversationContext
from domain.reasoning.value_objects.question import Question
from domain.reasoning.value_objects.request_plan import (
    ActionType,
    CognitivePlan,
    ExecutionStep,
    ExtractedEntities,
    IntentCategory,
    PendingOperation,
    TargetAgent,
)
from infrastructure.llm.openrouter_client import OpenRouterClient

logger = logging.getLogger(__name__)


_PLANNER_SYSTEM_PROMPT = """You are the Centralized Cognitive Planner for POLIS, an AI Organizational Intelligence Assistant.
Your task is to analyze employee requests and produce a validated, structured cognitive execution plan.

POLIS has the following specialist capabilities and target agents:
1. 'knowledge_agent': Handbooks, organizational policies, design architecture, company documentation, verified factual queries.
2. 'operations_agent': Task management, operational decisions, risk tracking, and action items.
3. 'calendar_agent': Calendar queries, scheduling meetings, event coordination, attendee availability.
4. 'governance_agent': Compliance policies, approvals, violations, governance rules.
5. 'activity_service': Real-time work status, break tracking, shift start/end times.
6. 'reminder_service': Setting personal or channel reminders.
7. 'general_reasoner': Historical communications, multi-agent synthesis, conversational greetings, clarifications, employee work queries.
8. Person-specific recent work, current tasks, commitments, blockers, or completed work queries (for self or specific colleagues) MUST be planned with intent 'employee_work_query' targeting 'general_reasoner'.

Rules for planning:
1. Select ONLY the specialists required for the request. Do not include unnecessary agents.
2. Determine if the request requires reading information ('read'), creating an item ('create'), updating an item ('update'), cancelling ('cancel'), or clarifying missing info ('clarify').
3. For actions (e.g. creating calendar events or tasks), identify if essential information is missing:
   - Calendar scheduling requires: title/summary, date, and time. If date or time is missing, set requires_clarification=true and list missing fields in missing_information.
   - Task creation requires: task summary. If missing, set requires_clarification=true.
4. If the request is ambiguous or lacks required parameters, set requires_clarification=true, provide a polite clarification_prompt, and do NOT authorize actions.
5. Support multi-step plans with explicit dependencies where step_2 depends on step_1.
6. NO CHAIN OF THOUGHT. Output ONLY a valid JSON object matching the schema below. No markdown fences, no explanatory text.

Schema:
{
  "request_id": "<request_id>",
  "original_message": "<original_message>",
  "intent": "<intent_category>",
  "intent_confidence": 1.0,
  "requested_outcome": "<short description>",
  "entities": {
    "employee_names": [],
    "target_user_id": null,
    "target_user_name": null,
    "team_names": [],
    "project_names": [],
    "dates": [],
    "times": [],
    "duration_minutes": null,
    "event_title": null,
    "audience_type": null,
    "audience_id": null,
    "task_summary": null,
    "item_reference": null,
    "extra_params": {}
  },
  "required_agents": ["<agent_name>"],
  "execution_steps": [
    {
      "step_id": "step_1",
      "agent": "<agent_name>",
      "action": "<action_name>",
      "action_type": "read",
      "parameters": {},
      "dependencies": []
    }
  ],
  "missing_information": [],
  "requires_clarification": false,
  "clarification_prompt": null,
  "action_required": false,
  "risk_level": "low"
}
"""


class CognitivePlanner:
    """
    Centralized cognitive planner for POLIS.

    Interprets natural language employee requests, extracts entities and parameters,
    detects missing required fields, manages pending conversational operations,
    and produces a validated structured CognitivePlan for selective specialist execution.
    """

    def __init__(
        self,
        llm_client: OpenRouterClient | None = None,
        default_timezone: ZoneInfo | None = None,
        identity_service: Any | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._default_timezone = default_timezone or ZoneInfo("Asia/Kolkata")
        self._identity_service = identity_service

    def plan(
        self,
        question: Question | str,
        context: ConversationContext | None = None,
    ) -> CognitivePlan:
        """
        Produce a validated structured CognitivePlan for the request.
        """
        target_user_id = None
        target_user_name = None
        if isinstance(question, Question):
            raw_text = question.text or ""
            ctx = context or question.context
            req_user = question.user_id or (ctx.user_id if ctx else None)
            target_user_id = question.target_user_id
            target_user_name = question.target_user_name
        else:
            raw_text = str(question)
            ctx = context
            req_user = ctx.user_id if ctx else None

        text = raw_text.strip()
        request_id = f"plan_{uuid.uuid4().hex[:12]}"

        # ------------------------------------------------------------------
        # 1. PENDING OPERATION CONTINUATION / CANCELLATION
        # ------------------------------------------------------------------
        pending: PendingOperation | None = None
        if ctx is not None:
            pending = ctx.get_typed_pending_operation(
                expected_user_id=req_user,
                expected_channel_id=ctx.channel_id,
                expected_thread_ts=getattr(ctx, "expected_thread_ts", None),
            )

        if pending is not None:
            # Check for cancellation
            if self._is_cancel_request(text):
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.CANCEL_ACTION,
                    intent_confidence=1.0,
                    requested_outcome=f"Cancel active operation '{pending.operation_id}'",
                    entities=ExtractedEntities(),
                    required_agents=[pending.target_agent],
                    execution_steps=[
                        ExecutionStep(
                            step_id="step_1",
                            agent=pending.target_agent,
                            action=pending.action or "cancel",
                            action_type=ActionType.CANCEL,
                            parameters={"operation_id": pending.operation_id},
                        )
                    ],
                    missing_information=[],
                    requires_clarification=False,
                    clarification_prompt=None,
                    action_required=True,
                    risk_level="low",
                )

            # Follow-up continuation to resolve missing fields
            return self._plan_pending_continuation(request_id, text, pending)

        # ------------------------------------------------------------------
        # 2. DETERMINISTIC FAST-PATHS
        # ------------------------------------------------------------------
        greeting_plan = self._check_greeting_fast_path(request_id, text)
        if greeting_plan is not None:
            return greeting_plan

        activity_plan = self._check_activity_fast_path(request_id, text)
        if activity_plan is not None:
            return activity_plan

        # ------------------------------------------------------------------
        # 3. LLM-BASED PLANNING (with semantic interpretation)
        # ------------------------------------------------------------------
        if self._llm_client is not None:
            try:
                llm_plan = self._plan_with_llm(request_id, text, ctx, req_user)
                if llm_plan is not None:
                    return llm_plan
            except Exception as e:
                logger.warning(
                    "LLM cognitive planning failed; falling back to deterministic planning: %s",
                    e,
                )

        # ------------------------------------------------------------------
        # 4. DETERMINISTIC FALLBACK PLANNER
        # ------------------------------------------------------------------
        return self._plan_deterministic(
            request_id=request_id,
            text=text,
            ctx=ctx,
            req_user=req_user,
            target_user_id=target_user_id,
            target_user_name=target_user_name,
        )

    # ======================================================================
    # PENDING CONTINUATION
    # ======================================================================

    def _plan_pending_continuation(
        self,
        request_id: str,
        text: str,
        pending: PendingOperation,
    ) -> CognitivePlan:
        # ------------------------------------------------------------------
        # Multi-step plan continuation (Stage B5.4)
        # ------------------------------------------------------------------
        if pending.is_multi_step:
            if pending.state_version != 1:
                logger.error("Unknown pending state_version %d (supported: 1).", pending.state_version)
                return CognitivePlan(
                    request_id=pending.plan_id or request_id,
                    original_message=text,
                    intent=IntentCategory.GENERAL_CONVERSATION,
                    intent_confidence=1.0,
                    requested_outcome="Incompatible pending state version",
                    missing_information=[],
                    requires_clarification=False,
                    clarification_prompt=None,
                    action_required=False,
                )

            orig_plan = pending.get_original_plan()
            if orig_plan is None:
                logger.error("Pending multi-step operation '%s' has corrupt or invalid plan.", pending.operation_id)
                return CognitivePlan(
                    request_id=pending.plan_id or request_id,
                    original_message=text,
                    intent=IntentCategory.GENERAL_CONVERSATION,
                    intent_confidence=1.0,
                    requested_outcome="Corrupt pending state recovery",
                    missing_information=[],
                    requires_clarification=False,
                    clarification_prompt=None,
                    action_required=False,
                )

            # Target step awaiting clarification
            target_step = None
            if pending.pending_step_id:
                target_step = next((s for s in orig_plan.execution_steps if s.step_id == pending.pending_step_id), None)
            if target_step is None and orig_plan.execution_steps:
                target_step = orig_plan.execution_steps[0]

            extracted = self.extract_entities(text)
            merged_entities = dict(pending.collected_entities)
            if extracted.dates:
                merged_entities["dates"] = list(dict.fromkeys(merged_entities.get("dates", []) + extracted.dates))
                if target_step:
                    target_step.parameters["dates"] = merged_entities["dates"]
                    target_step.parameters["date"] = merged_entities["dates"][0]
            if extracted.times:
                merged_entities["times"] = list(dict.fromkeys(merged_entities.get("times", []) + extracted.times))
                if target_step:
                    target_step.parameters["times"] = merged_entities["times"]
                    target_step.parameters["time"] = merged_entities["times"][0]
                    target_step.parameters["start_time"] = merged_entities["times"][0]
            if extracted.employee_names:
                merged_entities["employee_names"] = list(dict.fromkeys(merged_entities.get("employee_names", []) + extracted.employee_names))
                if target_step:
                    target_step.parameters["employee_names"] = merged_entities["employee_names"]
            if extracted.event_title:
                merged_entities["event_title"] = extracted.event_title
                if target_step:
                    target_step.parameters["title"] = extracted.event_title
            if extracted.task_summary:
                merged_entities["task_summary"] = extracted.task_summary
                if target_step:
                    target_step.parameters["summary"] = extracted.task_summary
            if extracted.audience_id:
                merged_entities["audience_id"] = extracted.audience_id
                if target_step:
                    target_step.parameters["audience_id"] = extracted.audience_id
            if extracted.duration_minutes:
                merged_entities["duration_minutes"] = extracted.duration_minutes
                if target_step:
                    target_step.parameters["duration_minutes"] = extracted.duration_minutes
            if extracted.item_reference:
                merged_entities["item_reference"] = extracted.item_reference
                if target_step:
                    target_step.parameters["task_id"] = extracted.item_reference

            # If text is a direct answer for missing summary
            if any("summary" in f.lower() for f in pending.missing_fields) and not extracted.task_summary:
                cleaned_text = text.strip()
                if cleaned_text and not self._is_cancel_request(cleaned_text):
                    merged_entities["task_summary"] = cleaned_text
                    if target_step:
                        target_step.parameters["summary"] = cleaned_text

            if any("target" in f.lower() for f in pending.missing_fields):
                m_obj = re.search(r"\b(?:on|target|resource)\s+([a-zA-Z0-9_:.-]+)", text, re.IGNORECASE)
                target_obj = m_obj.group(1).strip() if m_obj else (text.strip() if not self._is_cancel_request(text.strip()) else None)
                if target_obj:
                    merged_entities["target_object"] = target_obj
                    if target_step:
                        target_step.parameters["target_object"] = target_obj

            # Compute remaining missing fields for target step
            remaining_missing = []
            for field in pending.missing_fields:
                f_lower = field.lower()
                has_date = bool(merged_entities.get("dates") or (target_step and (target_step.parameters.get("date") or target_step.parameters.get("dates"))))
                has_time = bool(merged_entities.get("times") or (target_step and (target_step.parameters.get("time") or target_step.parameters.get("times") or target_step.parameters.get("start_time"))))
                has_title = bool(merged_entities.get("event_title") or (target_step and (target_step.parameters.get("title") or target_step.parameters.get("event_title"))))
                has_summary = bool(merged_entities.get("task_summary") or (target_step and (target_step.parameters.get("summary") or target_step.parameters.get("task_summary"))))
                has_target = bool(merged_entities.get("target_object") or (target_step and (target_step.parameters.get("target_object") or target_step.parameters.get("target"))))

                if any(k in f_lower for k in ("date", "dates")) and not has_date:
                    remaining_missing.append(field)
                elif any(k in f_lower for k in ("time", "times", "start_time")) and not has_time:
                    remaining_missing.append(field)
                elif any(k in f_lower for k in ("title", "event_title")) and not has_title:
                    remaining_missing.append(field)
                elif any(k in f_lower for k in ("task_summary", "summary")) and not has_summary:
                    remaining_missing.append(field)
                elif any(k in f_lower for k in ("target_object", "target")) and not has_target:
                    remaining_missing.append(field)
                elif not any(k in f_lower for k in ("date", "dates", "time", "times", "start_time", "title", "event_title", "task_summary", "summary", "target_object", "target")):
                    if target_step and field not in target_step.parameters and (field not in merged_entities or not merged_entities[field]):
                        remaining_missing.append(field)

            if remaining_missing:
                clarification = self._generate_clarification_prompt(remaining_missing, pending)
                return CognitivePlan(
                    request_id=pending.plan_id or orig_plan.request_id,
                    original_message=text,
                    intent=orig_plan.intent,
                    intent_confidence=1.0,
                    requested_outcome=f"Continue multi-step plan '{pending.plan_id}' (pending missing fields)",
                    entities=extracted,
                    required_agents=orig_plan.required_agents,
                    execution_steps=orig_plan.execution_steps,
                    missing_information=remaining_missing,
                    requires_clarification=True,
                    clarification_prompt=clarification,
                    action_required=False,
                    risk_level=orig_plan.risk_level,
                )

            return CognitivePlan(
                request_id=pending.plan_id or orig_plan.request_id,
                original_message=text,
                intent=orig_plan.intent,
                intent_confidence=1.0,
                requested_outcome=f"Resume multi-step plan '{pending.plan_id}'",
                entities=extracted,
                required_agents=orig_plan.required_agents,
                execution_steps=orig_plan.execution_steps,
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=True,
                risk_level=orig_plan.risk_level,
            )

        # ------------------------------------------------------------------
        # Single-step plan continuation (Legacy baseline)
        # ------------------------------------------------------------------
        extracted = self.extract_entities(text)
        merged_entities = dict(pending.collected_entities)

        # Merge newly extracted non-empty fields
        if extracted.dates:
            merged_entities["dates"] = list(
                dict.fromkeys(merged_entities.get("dates", []) + extracted.dates)
            )
        if extracted.times:
            merged_entities["times"] = list(
                dict.fromkeys(merged_entities.get("times", []) + extracted.times)
            )
        if extracted.employee_names:
            merged_entities["employee_names"] = list(
                dict.fromkeys(
                    merged_entities.get("employee_names", [])
                    + extracted.employee_names
                )
            )
        if extracted.event_title:
            merged_entities["event_title"] = extracted.event_title
        if extracted.task_summary:
            merged_entities["task_summary"] = extracted.task_summary
        if extracted.audience_id:
            merged_entities["audience_id"] = extracted.audience_id
        if extracted.duration_minutes:
            merged_entities["duration_minutes"] = extracted.duration_minutes

        if any("summary" in f.lower() for f in pending.missing_fields) and not extracted.task_summary:
            cleaned_text = text.strip()
            if cleaned_text and not self._is_cancel_request(cleaned_text):
                merged_entities["task_summary"] = cleaned_text
                merged_entities["summary"] = cleaned_text

        if any("target" in f.lower() for f in pending.missing_fields):
            m_obj = re.search(r"\b(?:on|target|resource)\s+([a-zA-Z0-9_:.-]+)", text, re.IGNORECASE)
            target_obj = m_obj.group(1).strip() if m_obj else (text.strip() if not self._is_cancel_request(text.strip()) else None)
            if target_obj:
                merged_entities["target_object"] = target_obj

        # Check remaining missing fields
        remaining_missing: list[str] = []
        for field in pending.missing_fields:
            if field in ("date", "dates") and not merged_entities.get("dates"):
                remaining_missing.append(field)
            elif field in ("time", "times") and not merged_entities.get("times"):
                remaining_missing.append(field)
            elif field in ("title", "event_title") and not (merged_entities.get("event_title") or merged_entities.get("title")):
                remaining_missing.append(field)
            elif field in ("task_summary", "summary") and not (merged_entities.get("task_summary") or merged_entities.get("summary")):
                remaining_missing.append(field)
            elif field in ("target_object", "target") and not (merged_entities.get("target_object") or merged_entities.get("target")):
                remaining_missing.append(field)
            elif field not in ("date", "dates", "time", "times", "title", "event_title", "task_summary", "summary", "target_object", "target"):
                if field not in merged_entities or not merged_entities[field]:
                    remaining_missing.append(field)

        if remaining_missing:
            # Still missing required fields
            clarification = self._generate_clarification_prompt(remaining_missing, pending)
            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.CLARIFICATION_RESPONSE,
                intent_confidence=1.0,
                requested_outcome=f"Continue pending operation '{pending.operation_id}' with missing details",
                entities=extracted,
                required_agents=[pending.target_agent],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=pending.target_agent,
                        action=pending.action,
                        action_type=ActionType.CLARIFY,
                        parameters={
                            "operation_id": pending.operation_id,
                            "collected_entities": merged_entities,
                            "missing_fields": remaining_missing,
                        },
                    )
                ],
                missing_information=remaining_missing,
                requires_clarification=True,
                clarification_prompt=clarification,
                action_required=False,
                risk_level="low",
            )

        # All missing fields satisfied -> authorize execution step
        action_type = ActionType.CREATE
        if pending.intent == IntentCategory.TASK_ACTION and "update" in pending.action:
            action_type = ActionType.UPDATE
        if "task_summary" in merged_entities and "summary" not in merged_entities:
            merged_entities["summary"] = merged_entities["task_summary"]

        return CognitivePlan(
            request_id=request_id,
            original_message=text,
            intent=pending.intent,
            intent_confidence=1.0,
            requested_outcome=f"Execute pending operation '{pending.operation_id}' with resolved parameters",
            entities=extracted,
            required_agents=[pending.target_agent],
            execution_steps=[
                ExecutionStep(
                    step_id="step_1",
                    agent=pending.target_agent,
                    action=pending.action,
                    action_type=action_type,
                    parameters=merged_entities,
                )
            ],
            missing_information=[],
            requires_clarification=False,
            clarification_prompt=None,
            action_required=True,
            risk_level="low",
        )

    # ======================================================================
    # FAST PATHS
    # ======================================================================

    @staticmethod
    def _is_cancel_request(text: str) -> bool:
        norm = text.lower().strip().rstrip(".!?")
        norm = re.sub(r"[,;:]", " ", norm)
        cancel_patterns = (
            r"\b(?:cancel|abort)\b",
            r"\b(?:never\s*mind|nevermind|forget\s*it|don'?t\s+worry)\b",
            r"^(?:stop|exit|quit|no\s*thanks)$",
            r"\bstop\s+(?:the|this|that)?\s*(?:operation|action|event|meeting|task)?\b",
        )
        return any(re.search(pat, norm) for pat in cancel_patterns)


    @staticmethod
    def _check_greeting_fast_path(request_id: str, text: str) -> CognitivePlan | None:
        norm = text.lower().strip().rstrip(".!?")
        norm = re.sub(r"^<@[a-z0-9_|-]+>\s*[,:]?\s*", "", norm)
        norm = re.sub(r"^@polis\s*[,:]?\s*", "", norm)
        norm = norm.strip(" :,;—–-")
        greeting_patterns = (
            r"^(?:hi|hello|hey|hiya|howdy)(?:[\s,]+(?:polis|there|team|everyone|all|folks|<@[a-z0-9_|-]+>|@[a-z0-9_.-]+))?$",
            r"^(?:good\s+(?:morning|afternoon|evening|day)|morning|afternoon|evening)(?:[\s,]+(?:polis|there|team|everyone|all|folks|<@[a-z0-9_|-]+>|@[a-z0-9_.-]+))?$",
            r"^(?:thanks|thank\s+you|thx)(?:[\s,]+(?:polis|there|team|everyone|all|folks))?$",
            r"^(?:bye|goodbye|see\s+ya|talk\s+later|see\s+you(?:\s+tomorrow|\s+later)?|good\s*night)(?:[\s,]+(?:polis|there|team|everyone|all|folks))?$",
            r"^(?:have\s+a\s+(?:good|nice)\s+(?:day|evening|weekend|one))(?:[\s,]+(?:polis|there|team|everyone|all|folks))?$",
            r"^(?:(?:i'?m\s+|i\s+am\s+)?(?:signing|logging)\s+off(?:\s+for\s+(?:today|the\s+day)|\s+now)?)(?:[\s,]+(?:polis|there|team|everyone|all|folks))?$",
            r"^(?:(?:i'?m\s+|i\s+am\s+)?(?:done|finished)(?:\s+for\s+(?:today|the\s+day)|\s+now|\s+working)?)(?:[\s,]+(?:polis|there|team|everyone|all|folks))?$",
            r"^(?:ending|stopping)\s+work(?:[\s,]+(?:polis|there|team|everyone|all|folks))?$",
            r"^(?:leaving\s+work|logging\s+out)(?:[\s,]+(?:polis|there|team|everyone|all|folks))?$",
            r"^(?:who\s+are\s+you|what\s+is\s+polis)$",
        )
        if any(re.match(pat, norm) for pat in greeting_patterns):
            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.GENERAL_CONVERSATION,
                intent_confidence=1.0,
                requested_outcome="Acknowledge conversational pleasantry or greeting",
                entities=ExtractedEntities(),
                required_agents=[TargetAgent.GENERAL_REASONER],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.GENERAL_REASONER,
                        action="conversation",
                        action_type=ActionType.READ,
                        parameters={"query": text},
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=False,
                risk_level="low",
            )
        return None

    @staticmethod
    def _check_activity_fast_path(request_id: str, text: str) -> CognitivePlan | None:
        norm = text.lower().strip().rstrip(".!?")
        activity_patterns = (
            r"^who\s+is\s+(?:currently\s+)?(?:working(?!\s+on\b)|on\s+break|active)",
            r"^is\s+<@[a-z0-9]+>\s+(?:currently\s+)?(?:working|on\s+break)",
            r"^is\s+[a-z0-9_.-]+\s+(?:currently\s+)?(?:working|on\s+break)",
            r"^what\s+is\s+the\s+status\s+of\s+(?!that\b|it\b|this\b)",
            r"^when\s+did\s+.+\s+(?:start|begin)\s+work",
            r"^how\s+long\s+has\s+.+\s+been\s+working",
            r"^(?:attendance|work\s+status|break\s+status)\b",
        )
        if any(re.search(pat, norm) for pat in activity_patterns):
            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.ACTIVITY_STATUS_QUERY,
                intent_confidence=1.0,
                requested_outcome="Query live attendance or activity status",
                entities=ExtractedEntities(),
                required_agents=[TargetAgent.ACTIVITY_SERVICE],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.ACTIVITY_SERVICE,
                        action="query_activity",
                        action_type=ActionType.READ,
                        parameters={"query": text},
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=False,
                risk_level="low",
            )
        return None

    def _check_employee_work_query(
        self,
        request_id: str,
        text: str,
        norm: str,
        extracted: ExtractedEntities,
        ctx: ConversationContext | None,
        req_user: str | None,
        target_user_id: str | None = None,
        target_user_name: str | None = None,
    ) -> CognitivePlan | None:
        self_work_patterns = (
            r"\bwhat\s+(?:am\s+i|have\s+i\s+been)\s+(?:currently\s+)?working\s+on\b",
            r"\b(?:give\s+me\s+a\s+)?(?:summary\s+of\s+)?my\s+(?:current\s+)?(?:work|priorities|recent\s+work|tasks\s+and\s+priorities)\b",
            r"\bsummarize\s+my\s+(?:recent\s+)?work(?:\s+from\s+slack)?\b",
            r"\bwhat\s+(?:work|tasks)\s+(?:have\s+i|did\s+i)\s+(?:handled|completed|worked\s+on)(?:\s+recently|\s+this\s+week)?\b",
            r"\bwhat\s+(?:have\s+i|did\s+i)\s+completed(?:\s+recently|\s+this\s+week)?\b",
            r"\bwhat\s+am\s+i\s+blocked\s+on\b",
            r"\bwhat\s+(?:should|do)\s+i\s+work\s+on(?:\s+today)?\b",
            r"\bmy\s+recent\s+work\b",
            r"\bmy\s+current\s+work\b",
            r"\b(?:am\s+i|have\s+i)\s+(?:available|signed\s+off|on\s+break)\b",
            r"\bwhat\s+is\s+my\s+(?:schedule|availability|status)\b",
        )

        other_work_patterns = (
            r"\bwhat\s+is\s+(?:<@[a-z0-9_|-]+>|[a-z0-9_.-]+)\s+(?:currently\s+)?working\s+on\b",
            r"\bwhat\s+is\s+(?:<@[a-z0-9_|-]+>|[a-z0-9_.-]+)\s+blocked\s+on\b",
            r"\bwhat\s+(?:tasks\s+)?has\s+(?:<@[a-z0-9_|-]+>|[a-z0-9_.-]+)\s+(?:handled|completed|done|worked\s+on)(?:\s+recently|\s+this\s+week)?\b",
            r"\bwhat\s+has\s+(?:<@[a-z0-9_|-]+>|[a-z0-9_.-]+)\s+completed(?:\s+recently|\s+this\s+week)?\b",
            r"\b(?:give\s+me\s+a\s+)?(?:summary\s+of\s+)?(?:<@[a-z0-9_|-]+>|[a-z0-9_.-]+)'s\s+(?:current\s+)?(?:work|priorities|recent\s+work|tasks)\b",
            r"\bsummarize\s+(?:<@[a-z0-9_|-]+>|[a-z0-9_.-]+)(?:'s)?\s+(?:recent\s+)?work(?:\s+from\s+slack)?\b",
            r"\bwhat\s+is\s+this\s+person\s+(?:currently\s+)?(?:working|blocked)\s+on\b",
            r"\bwhat\s+is\s+this\s+person\s+working\s+on\b",
            # Availability, schedule, and sign-off queries
            r"\b(?:is|has)\s+(?:<@[a-z0-9_|-]+>|[a-z0-9_.-]+)\s+(?:available|online|signed\s+off|on\s+break|taking\s+a\s+break)\b",
            r"\bwhen\s+did\s+(?:<@[a-z0-9_|-]+>|[a-z0-9_.-]+)\s+(?:sign\s+off|leave|step\s+away)\b",
            r"\bwhat\s+is\s+(?:<@[a-z0-9_|-]+>|[a-z0-9_.-]+)'s\s+(?:schedule|availability|working\s+hours|status)\b",
            # Follow-up pronoun and anaphoric continuity patterns
            r"\bwhat\s+(?:has\s+he|has\s+she|have\s+they|did\s+he|did\s+she)\s+(?:completed|done|finished|worked\s+on|handled)(?:\s+recently|\s+this\s+week)?\b",
            r"\bwhat\s+(?:is|are)\s+(?:he|she|they)\s+(?:currently\s+)?working\s+on\b",
            r"\bwhat\s+(?:is|are)\s+(?:he|she|they)\s+blocked\s+on\b",
            r"\b(?:is|has)\s+(?:he|she|they)\s+(?:available|online|signed\s+off|on\s+break)\b",
            r"\bwhen\s+did\s+(?:he|she|they)\s+(?:sign\s+off|leave|step\s+away)\b",
            r"\bwhat\s+(?:tasks\s+)?(?:have\s+been\s+assigned\s+to|are\s+assigned\s+to)\s+(?:him|her|them)\b",
            r"\bwhat\s+progress\s+has\s+(?:he|she|they)\s+made\b",
            r"\bwhat\s+is\s+still\s+(?:pending|remaining|ongoing|in\s+progress|open)\b",
            r"\bwhat\s+(?:tasks?|work)\s+(?:is|are)\s+still\s+(?:pending|remaining|ongoing)\b",
            r"\bwhat\s+has\s+changed(?:\s+since\s+(?:the\s+)?(?:last|previous)\s+update)?\b",
            r"\bwhat\s+are\s+(?:his|her|their)\s+(?:priorities|tasks|responsibilities)\b",
        )

        is_self = any(re.search(pat, norm) for pat in self_work_patterns)
        is_other = any(re.search(pat, norm) for pat in other_work_patterns)

        if not is_self and not is_other:
            return None

        effective_target_id = target_user_id
        effective_target_name = target_user_name

        if is_self:
            effective_target_id = req_user
            effective_target_name = None
        else:
            named_person = None
            if extracted.employee_names:
                named_person = extracted.employee_names[0]
            elif any(p in norm for p in ("he", "him", "his", "she", "her", "they", "them", "their", "this person", "that person", "still pending", "remaining", "what has changed", "what progress")):
                if ctx and getattr(ctx, "history", None):
                    for msg in reversed(ctx.history):
                        meta = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
                        meta_name = meta.get("target_user_name") or msg.get("target_user_name")
                        meta_id = meta.get("target_user_id") or msg.get("target_user_id")
                        if meta_name:
                            named_person = meta_name
                            if meta_id:
                                effective_target_id = meta_id
                            break
                        if meta_id:
                            effective_target_id = meta_id
                            break
                        content = (msg.get("content") or "").strip()
                        m = re.search(r"\bwhat\s+(?:is|has)\s+([a-zA-Z0-9_.-]+)(?:\s+currently|\s+recently)?\s+(?:working|completed|done|handled|blocked)", content, re.IGNORECASE)
                        if m and m.group(1).lower() not in ("this", "that", "the", "he", "she", "they", "i", "we", "my", "your"):
                            named_person = m.group(1).strip()
                            break
                        m2 = re.search(r"\b(?:for|concerning|regarding|about)\s+([A-Z][a-zA-Z0-9_.-]+)\b", content)
                        if m2 and m2.group(1).lower() not in ("you", "me", "this", "that", "the"):
                            named_person = m2.group(1).strip()
                            break
                        if self._identity_service and hasattr(self._identity_service, "get_workspace_users"):
                            try:
                                for u in self._identity_service.get_workspace_users():
                                    for un in [u.get("profile", {}).get("display_name"), u.get("real_name"), u.get("name")]:
                                        if un and len(un) >= 2 and re.search(rf"\b{re.escape(un.lower())}\b", content.lower()):
                                            named_person = u.get("profile", {}).get("display_name") or u.get("real_name") or u.get("name")
                                            effective_target_id = u["id"]
                                            break
                                    if named_person:
                                        break
                            except Exception:
                                pass
                        if named_person:
                            break
                named_person = named_person or "this person"

            if named_person and not effective_target_id:
                if named_person.startswith("U") and len(named_person) >= 8 and named_person[1:].isalnum():
                    effective_target_id = named_person
                elif self._identity_service is not None:
                    try:
                        users = self._identity_service.get_workspace_users()
                        matches = []
                        for u in users:
                            disp = u.get("profile", {}).get("display_name") or ""
                            real = u.get("real_name") or ""
                            uname = u.get("name") or ""
                            candidates = {disp.lower(), real.lower(), uname.lower()}
                            if any(named_person.lower() == c or named_person.lower() in c.split() for c in candidates if c):
                                matches.append(u)

                        if len(matches) > 1:
                            candidate_names = [
                                (u.get("profile", {}).get("display_name") or u.get("real_name") or u.get("name") or u["id"])
                                for u in matches
                            ]
                            cand_str = ", ".join(f"`{c}`" for c in candidate_names)
                            return CognitivePlan(
                                request_id=request_id,
                                original_message=text,
                                intent=IntentCategory.EMPLOYEE_WORK_QUERY,
                                intent_confidence=0.95,
                                requested_outcome="Clarify ambiguous employee identity",
                                entities=extracted,
                                required_agents=[TargetAgent.GENERAL_REASONER],
                                execution_steps=[],
                                missing_information=["target_user_id"],
                                requires_clarification=True,
                                clarification_prompt=f"Multiple team members match that name ({cand_str}). Could you please clarify which person you mean?",
                                action_required=False,
                                risk_level="low",
                            )
                        elif len(matches) == 1:
                            effective_target_id = matches[0]["id"]
                            effective_target_name = (
                                matches[0].get("profile", {}).get("display_name")
                                or matches[0].get("real_name")
                                or matches[0].get("name")
                            )
                        else:
                            effective_target_name = named_person
                    except Exception as err:
                        logger.warning("Identity lookup in planner failed: %s", err)
                        effective_target_name = named_person
                else:
                    effective_target_name = named_person

        target_display = effective_target_name or effective_target_id or ("you" if is_self else "employee")
        extracted_copy = extracted.model_copy()
        extracted_copy.target_user_id = effective_target_id
        extracted_copy.target_user_name = effective_target_name

        return CognitivePlan(
            request_id=request_id,
            original_message=text,
            intent=IntentCategory.EMPLOYEE_WORK_QUERY,
            intent_confidence=0.95,
            requested_outcome=f"Retrieve recent work and task activity for {target_display}",
            entities=extracted_copy,
            required_agents=[TargetAgent.GENERAL_REASONER],
            execution_steps=[
                ExecutionStep(
                    step_id="step_1",
                    agent=TargetAgent.GENERAL_REASONER,
                    action="get_person_recent_activity",
                    action_type=ActionType.READ,
                    parameters={
                        "target_user_id": effective_target_id,
                        "target_user_name": effective_target_name,
                        "requester_user_id": req_user,
                    },
                )
            ],
            missing_information=[],
            requires_clarification=False,
            clarification_prompt=None,
            action_required=False,
            risk_level="low",
        )

    # ======================================================================
    # LLM-BASED PLANNING
    # ======================================================================

    def _plan_with_llm(
        self,
        request_id: str,
        text: str,
        ctx: ConversationContext | None,
        req_user: str | None,
    ) -> CognitivePlan | None:
        """
        Produce a plan using semantic LLM interpretation.
        """
        assert self._llm_client is not None

        history_context = ""
        if ctx is not None and ctx.history:
            recent = ctx.history[-6:]
            history_lines = []
            for item in recent:
                sender = item.get("user") or item.get("role", "unknown")
                msg = item.get("content") or item.get("text", "")
                history_lines.append(f"{sender}: {msg}")
            if history_lines:
                history_context = "\nRecent Conversation History:\n" + "\n".join(history_lines)

        user_prompt = (
            f"Employee Request: \"{text}\"\n"
            f"Requester User ID: \"{req_user or 'unknown'}\"\n"
            f"Request ID: \"{request_id}\"\n"
            f"{history_context}\n\n"
            f"Produce the structured CognitivePlan JSON:"
        )

        full_prompt = f"{_PLANNER_SYSTEM_PROMPT}\n\n{user_prompt}"
        raw_response = self._llm_client.generate(full_prompt)

        clean_text = raw_response.strip()
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text)
            clean_text = re.sub(r"\s*```$", "", clean_text)

        try:
            parsed = json.loads(clean_text)
            if not isinstance(parsed, dict):
                return None

            # Enforce request_id and original_message
            parsed["request_id"] = request_id
            parsed["original_message"] = text

            # Validate against typed Pydantic CognitivePlan model
            return CognitivePlan.model_validate(parsed)
        except Exception as e:
            logger.warning("Failed to validate LLM plan output: %s (Output: %s)", e, clean_text[:200])
            return None

    # ======================================================================
    # DETERMINISTIC PLANNING FALLBACK
    # ======================================================================

    def _plan_deterministic(
        self,
        request_id: str,
        text: str,
        ctx: ConversationContext | None,
        req_user: str | None,
        target_user_id: str | None = None,
        target_user_name: str | None = None,
    ) -> CognitivePlan:
        """
        Robust deterministic planner when LLM is unavailable or yields malformed output.
        """
        norm = text.lower()
        extracted = self.extract_entities(text)

        # ------------------------------------------------------------------
        # Deterministic Planner Multi-Turn Continuation Safeguards
        # ------------------------------------------------------------------
        is_topic_change = bool(
            re.search(
                r"^\s*(?:now\s+let'?s\s+(?:discuss|talk\s+about|move\s+to)|on\s+another\s+note|changing\s+topics?|switch\s+topics?|unrelated|different\s+question|by\s+the\s+way)\b",
                norm,
            )
        )

        # Consequential action safeguard: Never execute a consequential action solely because an entity was inferred from history
        consequential_anaphoric_match = re.search(
            r"^(?:cancel|delete|remove|abort|terminate)\s+(?:it|that|this|(?:the|that|this)\s+(?:meeting|event|task|item|action|operation))\s*$",
            norm,
        )
        if consequential_anaphoric_match:
            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.CANCEL_ACTION,
                intent_confidence=0.9,
                requested_outcome="Clarify target item for cancellation",
                entities=extracted,
                required_agents=[TargetAgent.GENERAL_REASONER],
                execution_steps=[],
                missing_information=["item_reference"],
                requires_clarification=True,
                clarification_prompt="Which item would you like to cancel? Please specify the title or ID.",
                action_required=False,
                risk_level="low",
            )

        # Multi-turn context resolution when conversation context is present and topic has not changed
        if ctx is not None and ctx.history and not is_topic_change:
            recent_msgs = ctx.history[-4:]
            antecedents_found: list[str] = []
            for msg in reversed(recent_msgs):
                content = msg.get("content", "")
                if "task" in content.lower():
                    antecedents_found.append("task")
                if "calendar" in content.lower() or "meeting" in content.lower():
                    antecedents_found.append("calendar")
                if "policy" in content.lower() or "violation" in content.lower() or "approval" in content.lower():
                    antecedents_found.append("governance")
            distinct_types = set(antecedents_found)

            latest_msg_content = recent_msgs[-1].get("content", "") if recent_msgs else ""
            tasks_found = re.findall(r"(?:Operational item:\s*task.*?Summary:\s*([^\n]+)|task\s+['\"][^'\"]+['\"])", latest_msg_content, re.IGNORECASE | re.DOTALL)
            cal_found = re.findall(r"(?:Calendar Entry\s*\[[^\]]+\]:\s*['\"][^'\"]+['\"]|meeting\s+['\"][^'\"]+['\"])", latest_msg_content, re.IGNORECASE)
            gov_found = re.findall(r"\b([A-Z]{2,6}-\d{2,4})\b", latest_msg_content)
            multi_entities_in_domain = len(tasks_found) > 1 or len(cal_found) > 1 or len(set(gov_found)) > 1

            generic_anaphoric_query = bool(
                re.search(
                    r"^\s*(?:what\s+(?:is\s+the\s+status(?:\s+of\s+that)?|about\s+that)|who\s+(?:owns\s+that|is\s+(?:working\s+on\s+that|assigned(?:\s+to\s+that)?|attending(?:\s+that)?))|tell\s+me\s+more(?:\s+about\s+that)?)\s*[\?\.]*\s*$",
                    norm,
                )
            )
            # If multiple plausible antecedents exist and query is generic, ask for clarification
            if generic_anaphoric_query and (len(distinct_types) > 1 or multi_entities_in_domain):
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.GENERAL_CONVERSATION,
                    intent_confidence=0.85,
                    requested_outcome="Clarify ambiguous antecedent",
                    entities=extracted,
                    required_agents=[TargetAgent.GENERAL_REASONER],
                    execution_steps=[],
                    missing_information=["item_reference"],
                    requires_clarification=True,
                    clarification_prompt="Could you please clarify which item you are referring to?",
                    action_required=False,
                    risk_level="low",
                )

            # Unambiguous calendar follow-up query
            cal_followup = bool(
                re.search(
                    r"\b(?:who\s+is\s+(?:attending|invited)|when\s+is\s+(?:it|that|the\s+meeting)|what\s+time\s+is\s+(?:it|that|the\s+meeting))\b",
                    norm,
                )
            )
            if cal_followup and any("calendar" in m.get("content", "").lower() or "meeting" in m.get("content", "").lower() for m in recent_msgs):
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.CALENDAR_QUERY,
                    intent_confidence=0.9,
                    requested_outcome="Retrieve calendar schedule or events for follow-up",
                    entities=extracted,
                    required_agents=[TargetAgent.CALENDAR_AGENT],
                    execution_steps=[
                        ExecutionStep(
                            step_id="step_1",
                            agent=TargetAgent.CALENDAR_AGENT,
                            action="query_events",
                            action_type=ActionType.READ,
                            parameters={"query": text, "dates": extracted.dates},
                        )
                    ],
                    missing_information=[],
                    requires_clarification=False,
                    clarification_prompt=None,
                    action_required=False,
                    risk_level="low",
                )

            # Unambiguous task / operations follow-up query
            task_followup = bool(
                re.search(
                    r"\b(?:who\s+is\s+(?:assigned|working\s+on\s+(?:it|that|this|that\s+task))|who\s+owns\s+(?:it|that|this)|are\s+any\s+(?:of\s+them\s+|of\s+those\s+)?overdue|what\s+is\s+the\s+status\s+of\s+that\s+task|break\s+(?:it\s+)?down|actionable\s+steps?|help\s+(?:me\s+)?(?:start|break\s+it\s+down)|next\s+steps?|what\s+should\s+i\s+do\s+first)\b",
                    norm,
                )
            )
            if task_followup and any("task" in m.get("content", "").lower() for m in recent_msgs):
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.TASK_QUERY,
                    intent_confidence=0.9,
                    requested_outcome="Query organizational tasks for follow-up",
                    entities=extracted,
                    required_agents=[TargetAgent.OPERATIONS_AGENT],
                    execution_steps=[
                        ExecutionStep(
                            step_id="step_1",
                            agent=TargetAgent.OPERATIONS_AGENT,
                            action="query_tasks",
                            action_type=ActionType.READ,
                            parameters={"query": text},
                        )
                    ],
                    missing_information=[],
                    requires_clarification=False,
                    clarification_prompt=None,
                    action_required=False,
                    risk_level="low",
                )

            # Unambiguous governance follow-up query
            gov_followup = bool(
                re.search(
                    r"\b(?:what\s+is\s+the\s+severity|has\s+that\s+been\s+approved|is\s+that\s+approved|who\s+requested\s+that\s+approval)\b",
                    norm,
                )
            )
            if gov_followup and any("policy" in m.get("content", "").lower() or "violation" in m.get("content", "").lower() or "approval" in m.get("content", "").lower() for m in recent_msgs):
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.KNOWLEDGE_QUERY,
                    intent_confidence=0.85,
                    requested_outcome="Query compliance and governance policies for follow-up",
                    entities=extracted,
                    required_agents=[TargetAgent.GOVERNANCE_AGENT],
                    execution_steps=[
                        ExecutionStep(
                            step_id="step_1",
                            agent=TargetAgent.GOVERNANCE_AGENT,
                            action="query_governance",
                            action_type=ActionType.READ,
                            parameters={"query": text},
                        )
                    ],
                    missing_information=[],
                    requires_clarification=False,
                    clarification_prompt=None,
                    action_required=False,
                    risk_level="low",
                )

        # ------------------------------------------------------------------
        # A. Calendar Action: Schedule Event
        # ------------------------------------------------------------------
        schedule_match = re.search(
            r"\b(?:schedule|book|create|set\s*up)\s+(?:an?\s+)?(?:meeting|event|call|sync|session)\b",
            norm,
        )
        if schedule_match:
            missing_info: list[str] = []
            if not extracted.dates:
                missing_info.append("date")
            if not extracted.times:
                missing_info.append("time")

            event_title = extracted.event_title or "Meeting"
            if missing_info:
                prompt = self._generate_clarification_prompt(
                    missing_info,
                    operation_type="schedule",
                    title=event_title,
                )
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.CALENDAR_ACTION,
                    intent_confidence=0.9,
                    requested_outcome=f"Schedule calendar event '{event_title}' (pending missing details)",
                    entities=extracted,
                    required_agents=[TargetAgent.CALENDAR_AGENT],
                    execution_steps=[
                        ExecutionStep(
                            step_id="step_1",
                            agent=TargetAgent.CALENDAR_AGENT,
                            action="create_event",
                            action_type=ActionType.CLARIFY,
                            parameters={"missing_fields": missing_info, "title": event_title},
                        )
                    ],
                    missing_information=missing_info,
                    requires_clarification=True,
                    clarification_prompt=prompt,
                    action_required=False,
                    risk_level="low",
                )

            # All required parameters present
            params = {
                "title": event_title,
                "dates": extracted.dates,
                "times": extracted.times,
                "employee_names": extracted.employee_names,
            }
            if extracted.duration_minutes:
                params["duration_minutes"] = extracted.duration_minutes

            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.CALENDAR_ACTION,
                intent_confidence=0.95,
                requested_outcome=f"Schedule calendar event '{event_title}'",
                entities=extracted,
                required_agents=[TargetAgent.CALENDAR_AGENT],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.CALENDAR_AGENT,
                        action="create_event",
                        action_type=ActionType.CREATE,
                        parameters=params,
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=True,
                risk_level="low",
            )

        # ------------------------------------------------------------------
        # B. Calendar Query
        # ------------------------------------------------------------------
        calendar_query_match = re.search(
            r"\b(?:calendar|events?|meetings?|schedule|availability)\b",
            norm,
        )
        if calendar_query_match:
            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.CALENDAR_QUERY,
                intent_confidence=0.85,
                requested_outcome="Retrieve calendar schedule or events",
                entities=extracted,
                required_agents=[TargetAgent.CALENDAR_AGENT],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.CALENDAR_AGENT,
                        action="query_events",
                        action_type=ActionType.READ,
                        parameters={"query": text, "dates": extracted.dates},
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=False,
                risk_level="low",
            )

        # ------------------------------------------------------------------
        # C. Reminder Action
        # ------------------------------------------------------------------
        reminder_match = re.search(r"\b(?:remind\s+me|set\s+a\s+reminder)\b", norm)
        if reminder_match:
            missing_info = []
            if not extracted.dates and not extracted.times:
                missing_info.append("time")
            if missing_info:
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.REMINDER_ACTION,
                    intent_confidence=0.9,
                    requested_outcome="Set reminder (pending missing time)",
                    entities=extracted,
                    required_agents=[TargetAgent.REMINDER_SERVICE],
                    execution_steps=[
                        ExecutionStep(
                            step_id="step_1",
                            agent=TargetAgent.REMINDER_SERVICE,
                            action="create_reminder",
                            action_type=ActionType.CLARIFY,
                            parameters={"missing_fields": missing_info},
                        )
                    ],
                    missing_information=missing_info,
                    requires_clarification=True,
                    clarification_prompt="When would you like to be reminded?",
                    action_required=False,
                    risk_level="low",
                )

            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.REMINDER_ACTION,
                intent_confidence=0.9,
                requested_outcome="Schedule reminder",
                entities=extracted,
                required_agents=[TargetAgent.REMINDER_SERVICE],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.REMINDER_SERVICE,
                        action="create_reminder",
                        action_type=ActionType.CREATE,
                        parameters={"text": text, "dates": extracted.dates, "times": extracted.times},
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=True,
                risk_level="low",
            )

        # ------------------------------------------------------------------
        # D. Task Action
        # ------------------------------------------------------------------
        task_action_match = re.search(
            r"\b(?:create|add|assign)\s+(?:a\s+)?task\b",
            norm,
        )
        if task_action_match:
            task_summary = extracted.task_summary
            if not task_summary:
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.TASK_ACTION,
                    intent_confidence=0.85,
                    requested_outcome="Create task (pending summary)",
                    entities=extracted,
                    required_agents=[TargetAgent.OPERATIONS_AGENT],
                    execution_steps=[
                        ExecutionStep(
                            step_id="step_1",
                            agent=TargetAgent.OPERATIONS_AGENT,
                            action="create_task",
                            action_type=ActionType.CLARIFY,
                            parameters={"missing_fields": ["task_summary"]},
                        )
                    ],
                    missing_information=["task_summary"],
                    requires_clarification=True,
                    clarification_prompt="What is the task description or summary?",
                    action_required=False,
                    risk_level="low",
                )

            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.TASK_ACTION,
                intent_confidence=0.9,
                requested_outcome=f"Create task '{task_summary}'",
                entities=extracted,
                required_agents=[TargetAgent.OPERATIONS_AGENT],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.OPERATIONS_AGENT,
                        action="create_task",
                        action_type=ActionType.CREATE,
                        parameters={
                            "summary": task_summary,
                            "assignee": extracted.employee_names[0] if extracted.employee_names else None,
                        },
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=True,
                risk_level="low",
            )

        # ------------------------------------------------------------------
        # E. Multi-Agent Query (e.g. Decisions + Policies)
        # ------------------------------------------------------------------
        if re.search(r"\bdecisions?\b", norm) and re.search(r"\bpolicies?\b", norm):
            step_1 = ExecutionStep(
                step_id="step_1",
                agent=TargetAgent.OPERATIONS_AGENT,
                action="query_decisions",
                action_type=ActionType.READ,
                parameters={"query": text},
            )
            step_2 = ExecutionStep(
                step_id="step_2",
                agent=TargetAgent.GOVERNANCE_AGENT,
                action="query_policies",
                action_type=ActionType.READ,
                parameters={"query": text},
                dependencies=["step_1"],
            )
            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.MULTI_AGENT_QUERY,
                intent_confidence=0.9,
                requested_outcome="Retrieve correlated decisions and governance policies",
                entities=extracted,
                required_agents=[TargetAgent.OPERATIONS_AGENT, TargetAgent.GOVERNANCE_AGENT],
                execution_steps=[step_1, step_2],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=False,
                risk_level="low",
            )

        # ------------------------------------------------------------------
        # F. Task / Decision / Risk Queries (Operations)
        # ------------------------------------------------------------------
        if re.search(r"\b(?:decisions?|decided)\b", norm):
            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.DECISION_QUERY,
                intent_confidence=0.9,
                requested_outcome="Query organizational decisions",
                entities=extracted,
                required_agents=[TargetAgent.OPERATIONS_AGENT],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.OPERATIONS_AGENT,
                        action="query_decisions",
                        action_type=ActionType.READ,
                        parameters={"query": text},
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=False,
                risk_level="low",
            )

        # ------------------------------------------------------------------
        # E2. Person-Specific Recent Work & Task Queries (EMPLOYEE_WORK_QUERY)
        # ------------------------------------------------------------------
        employee_work_plan = self._check_employee_work_query(
            request_id=request_id,
            text=text,
            norm=norm,
            extracted=extracted,
            ctx=ctx,
            req_user=req_user,
            target_user_id=target_user_id,
            target_user_name=target_user_name,
        )
        if employee_work_plan is not None:
            return employee_work_plan

        if re.search(r"\b(?:tasks?|action\s+items?|todos?|actionable\s+steps?|break\s+(?:it\s+)?down)\b", norm):
            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.TASK_QUERY,
                intent_confidence=0.9,
                requested_outcome="Query organizational tasks",
                entities=extracted,
                required_agents=[TargetAgent.OPERATIONS_AGENT],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.OPERATIONS_AGENT,
                        action="query_tasks",
                        action_type=ActionType.READ,
                        parameters={"query": text},
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=False,
                risk_level="low",
            )

        if re.search(r"\b(?:risks?|blockers?|hazards?)\b", norm):
            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.RISK_QUERY,
                intent_confidence=0.9,
                requested_outcome="Query operational risks",
                entities=extracted,
                required_agents=[TargetAgent.OPERATIONS_AGENT],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.OPERATIONS_AGENT,
                        action="query_risks",
                        action_type=ActionType.READ,
                        parameters={"query": text},
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=False,
                risk_level="low",
            )

        # ------------------------------------------------------------------
        # G. Governance Actions (Request, Grant, Reject Approval)
        # ------------------------------------------------------------------
        # 1. Request Approval
        gov_request_match = re.search(
            r"\b(?:request|submit|ask\s+for|create)\s+(?:an?\s+)?approval\b",
            norm,
        )
        if gov_request_match:
            missing_info = []
            title = extracted.task_summary or extracted.event_title
            target_object = extracted.item_reference or (extracted.extra_params.get("target_object") if extracted.extra_params else None)

            if not title:
                m_title = re.search(r"\bapproval\s+for\s+([^,]+?)(?:\s+(?:on|for|in|at)\s+([a-zA-Z0-9_:.-]+))?$", text, re.IGNORECASE)
                if m_title:
                    title = m_title.group(1).strip()
                    if m_title.group(2) and not target_object:
                        target_object = m_title.group(2).strip()

            if not title:
                missing_info.append("title")
            if not target_object:
                m_obj = re.search(r"\b(?:on|target|resource)\s+([a-zA-Z0-9_:.-]+)", text, re.IGNORECASE)
                if m_obj:
                    target_object = m_obj.group(1).strip()
                else:
                    missing_info.append("target_object")

            if missing_info:
                prompt = (
                    "Could you please specify the approval title?"
                    if "title" in missing_info and "target_object" not in missing_info
                    else "Could you please specify the target object or resource for this approval request?"
                    if "target_object" in missing_info and "title" not in missing_info
                    else "Could you please specify the title and target object for the approval request?"
                )
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.GOVERNANCE_ACTION,
                    intent_confidence=0.9,
                    requested_outcome="Request approval (pending missing fields)",
                    entities=extracted,
                    required_agents=[TargetAgent.GOVERNANCE_AGENT],
                    execution_steps=[
                        ExecutionStep(
                            step_id="step_1",
                            agent=TargetAgent.GOVERNANCE_AGENT,
                            action="request_approval",
                            action_type=ActionType.CLARIFY,
                            parameters={"missing_fields": missing_info},
                        )
                    ],
                    missing_information=missing_info,
                    requires_clarification=True,
                    clarification_prompt=prompt,
                    action_required=False,
                    risk_level="low",
                )

            params = {
                "title": title,
                "target_object": target_object,
            }
            if extracted.extra_params:
                if "policy_id" in extracted.extra_params:
                    params["policy_id"] = extracted.extra_params["policy_id"]
                if "notes" in extracted.extra_params:
                    params["notes"] = extracted.extra_params["notes"]

            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.GOVERNANCE_ACTION,
                intent_confidence=0.95,
                requested_outcome=f"Request approval for '{title}' on '{target_object}'",
                entities=extracted,
                required_agents=[TargetAgent.GOVERNANCE_AGENT],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.GOVERNANCE_AGENT,
                        action="request_approval",
                        action_type=ActionType.CREATE,
                        parameters=params,
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=True,
                risk_level="low",
            )

        # 2. Grant Approval
        gov_grant_match = re.search(
            r"\b(?:grant|approve)\s+(?:the\s+)?(?:approval|request)\b",
            norm,
        )
        if gov_grant_match:
            approval_id = extracted.item_reference or (extracted.extra_params.get("approval_id") if extracted.extra_params else None)
            if not approval_id:
                m_id = re.search(r"\b(?:approval|request)\s+([a-zA-Z0-9_-]+)", text, re.IGNORECASE)
                if m_id:
                    approval_id = m_id.group(1).strip()

            if not approval_id:
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.GOVERNANCE_ACTION,
                    intent_confidence=0.9,
                    requested_outcome="Grant approval (pending approval ID)",
                    entities=extracted,
                    required_agents=[TargetAgent.GOVERNANCE_AGENT],
                    execution_steps=[
                        ExecutionStep(
                            step_id="step_1",
                            agent=TargetAgent.GOVERNANCE_AGENT,
                            action="grant_approval",
                            action_type=ActionType.CLARIFY,
                            parameters={"missing_fields": ["approval_id"]},
                        )
                    ],
                    missing_information=["approval_id"],
                    requires_clarification=True,
                    clarification_prompt="What is the ID of the approval request to grant?",
                    action_required=False,
                    risk_level="low",
                )

            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.GOVERNANCE_ACTION,
                intent_confidence=0.95,
                requested_outcome=f"Grant approval '{approval_id}'",
                entities=extracted,
                required_agents=[TargetAgent.GOVERNANCE_AGENT],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.GOVERNANCE_AGENT,
                        action="grant_approval",
                        action_type=ActionType.UPDATE,
                        parameters={"approval_id": approval_id},
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=True,
                risk_level="low",
            )

        # 3. Reject Approval
        gov_reject_match = re.search(
            r"\b(?:reject|deny)\s+(?:the\s+)?(?:approval|request)\b",
            norm,
        )
        if gov_reject_match:
            approval_id = extracted.item_reference or (extracted.extra_params.get("approval_id") if extracted.extra_params else None)
            if not approval_id:
                m_id = re.search(r"\b(?:approval|request)\s+([a-zA-Z0-9_-]+)", text, re.IGNORECASE)
                if m_id:
                    approval_id = m_id.group(1).strip()

            missing_info = []
            if not approval_id:
                missing_info.append("approval_id")

            reason = extracted.extra_params.get("reason") if extracted.extra_params else None
            if not reason:
                m_reason = re.search(r"\b(?:reason|because|due to)\s*[:=]?\s*(.+)$", text, re.IGNORECASE)
                if m_reason:
                    reason = m_reason.group(1).strip()

            if not reason:
                missing_info.append("reason")

            if missing_info:
                prompt = (
                    "Could you please provide the approval ID and a reason for rejection?"
                    if "approval_id" in missing_info and "reason" in missing_info
                    else "Could you please specify the ID of the approval request to reject?"
                    if "approval_id" in missing_info
                    else "Could you please provide a reason for rejecting this approval request?"
                )
                return CognitivePlan(
                    request_id=request_id,
                    original_message=text,
                    intent=IntentCategory.GOVERNANCE_ACTION,
                    intent_confidence=0.9,
                    requested_outcome="Reject approval (pending missing fields)",
                    entities=extracted,
                    required_agents=[TargetAgent.GOVERNANCE_AGENT],
                    execution_steps=[
                        ExecutionStep(
                            step_id="step_1",
                            agent=TargetAgent.GOVERNANCE_AGENT,
                            action="reject_approval",
                            action_type=ActionType.CLARIFY,
                            parameters={"missing_fields": missing_info},
                        )
                    ],
                    missing_information=missing_info,
                    requires_clarification=True,
                    clarification_prompt=prompt,
                    action_required=False,
                    risk_level="low",
                )

            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.GOVERNANCE_ACTION,
                intent_confidence=0.95,
                requested_outcome=f"Reject approval '{approval_id}'",
                entities=extracted,
                required_agents=[TargetAgent.GOVERNANCE_AGENT],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.GOVERNANCE_AGENT,
                        action="reject_approval",
                        action_type=ActionType.UPDATE,
                        parameters={"approval_id": approval_id, "reason": reason},
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=True,
                risk_level="low",
            )

        # ------------------------------------------------------------------
        # H. Governance / Compliance Queries
        # ------------------------------------------------------------------
        if re.search(r"\b(?:compliance|approval|policy\s+violation|audit|regulations?)\b", norm):
            return CognitivePlan(
                request_id=request_id,
                original_message=text,
                intent=IntentCategory.KNOWLEDGE_QUERY,
                intent_confidence=0.85,
                requested_outcome="Query compliance and governance policies",
                entities=extracted,
                required_agents=[TargetAgent.GOVERNANCE_AGENT],
                execution_steps=[
                    ExecutionStep(
                        step_id="step_1",
                        agent=TargetAgent.GOVERNANCE_AGENT,
                        action="query_governance",
                        action_type=ActionType.READ,
                        parameters={"query": text},
                    )
                ],
                missing_information=[],
                requires_clarification=False,
                clarification_prompt=None,
                action_required=False,
                risk_level="low",
            )

        # ------------------------------------------------------------------
        # H. Default: Knowledge Query / Organizational Q&A
        # ------------------------------------------------------------------
        return CognitivePlan(
            request_id=request_id,
            original_message=text,
            intent=IntentCategory.KNOWLEDGE_QUERY,
            intent_confidence=0.8,
            requested_outcome="Query organizational knowledge base and communications",
            entities=extracted,
            required_agents=[TargetAgent.KNOWLEDGE_AGENT, TargetAgent.GENERAL_REASONER],
            execution_steps=[
                ExecutionStep(
                    step_id="step_1",
                    agent=TargetAgent.KNOWLEDGE_AGENT,
                    action="retrieve_knowledge",
                    action_type=ActionType.READ,
                    parameters={"query": text},
                ),
                ExecutionStep(
                    step_id="step_2",
                    agent=TargetAgent.GENERAL_REASONER,
                    action="reason_communications",
                    action_type=ActionType.READ,
                    parameters={"query": text},
                    dependencies=["step_1"],
                ),
            ],
            missing_information=[],
            requires_clarification=False,
            clarification_prompt=None,
            action_required=False,
            risk_level="low",
        )

    # ======================================================================
    # ENTITY EXTRACTION
    # ======================================================================

    @classmethod
    def extract_entities(cls, text: str) -> ExtractedEntities:
        """
        Extract recognizable entities from request text.
        """
        dates: list[str] = []
        times: list[str] = []
        employee_names: list[str] = []
        duration_minutes: int | None = None
        event_title: str | None = None
        task_summary: str | None = None

        norm = text.strip()

        # Dates: relative and explicit
        date_matches = re.findall(
            r"\b(?:today|tomorrow|yesterday|next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b",
            norm,
            flags=re.IGNORECASE,
        )
        for dm in date_matches:
            if dm.lower() not in dates:
                dates.append(dm.lower())

        # Times
        time_matches = re.findall(
            r"\b(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)|(?:at\s+)?\d{1,2}:\d{2}|noon|midnight)\b",
            norm,
            flags=re.IGNORECASE,
        )
        for tm in time_matches:
            cleaned_time = re.sub(r"^at\s+", "", tm.strip(), flags=re.IGNORECASE)
            if cleaned_time.lower() not in times:
                times.append(cleaned_time.lower())

        # Duration
        dur_match = re.search(
            r"\b(\d+)\s*(?:min|mins|minute|minutes|hour|hours|hr|hrs)\b",
            norm,
            flags=re.IGNORECASE,
        )
        if dur_match:
            val = int(dur_match.group(1))
            unit = dur_match.group(0).lower()
            if "hour" in unit or "hr" in unit:
                duration_minutes = val * 60
            else:
                duration_minutes = val

        # Employee names / Slack mentions
        slack_mentions = re.findall(r"<@([A-Z0-9]+)>", text)
        for sm in slack_mentions:
            if sm not in employee_names:
                employee_names.append(sm)

        name_with_match = re.findall(
            r"\b(?:with|assigned\s+to|for)\s+([A-Z][a-z]+)\b",
            text,
        )
        for nm in name_with_match:
            if nm not in employee_names and nm.lower() not in ("today", "tomorrow", "yesterday", "noon"):
                employee_names.append(nm)

        # Work / task person query names: e.g. "What is Akshat working on?", "What has Gurkirat completed?"
        work_name_patterns = (
            r"\bwhat\s+is\s+([A-Z][a-z]+)\s+(?:currently\s+)?(?:working|blocked)\b",
            r"\bwhat\s+(?:tasks\s+)?has\s+([A-Z][a-z]+)\s+(?:handled|completed|done|worked\s+on)\b",
            r"\bwhat\s+has\s+([A-Z][a-z]+)\s+completed\b",
            r"\b(?:about|on)\s+([A-Z][a-z]+)(?:'s)?\s+(?:tasks?|work|priorities|blockers?)\b",
            r"\b([A-Z][a-z]+)'s\s+(?:tasks?|work|priorities|blockers?|activities|updates?)\b",
            r"\b(?:summarize|summary\s+of)\s+([A-Z][a-z]+)(?:'s)?\s+(?:work|tasks?|priorities)\b",
            r"\bwhat\s+is\s+([A-Z][a-z]+)\s+working\s+on\b",
        )
        stopwords = {
            "today", "tomorrow", "yesterday", "noon", "what", "slack", "can", "could",
            "please", "polis", "ivan", "canva", "this", "that", "the", "my", "me", "i",
            "he", "she", "they", "we", "all",
        }
        for pat in work_name_patterns:
            for nm in re.findall(pat, text, flags=re.IGNORECASE):
                if nm not in employee_names and nm.lower() not in stopwords:
                    employee_names.append(nm)

        # Event title
        title_match = re.search(
            r"\b(?:schedule|book|create)\s+(?:a\s+)?(?:meeting|event|call|sync|session)\s+(?:called|titled|about|for)\s+[\"']?([^\"'\n.,]+?)[\"']?(?:\s+(?:on|at|with|tomorrow|today|next|$)|$)",
            text,
            flags=re.IGNORECASE,
        )
        if title_match:
            event_title = title_match.group(1).strip()
        else:
            simple_event = re.search(
                r"\b(?:schedule|book)\s+[\"']?([A-Z][a-zA-Z0-9\s]+?)[\"']?\s+(?:on|at|with|tomorrow|today)",
                text,
            )
            if simple_event:
                event_title = simple_event.group(1).strip()

        # Task summary
        task_match = re.search(
            r"\b(?:create|add|assign)\s+(?:a\s+)?task\s*[:]\s*[\"']?([^\"'\n.,]+?)[\"']?(?:\s+assigned\s+to|$)",
            text,
            flags=re.IGNORECASE,
        )
        if not task_match:
            task_match = re.search(
                r"\b(?:create|add)\s+(?:a\s+)?task\s+(?:to\s+|for\s+)?[\"']([^\"'\n]+?)[\"']",
                text,
                flags=re.IGNORECASE,
            )
        if not task_match:
            task_match = re.search(
                r"\b(?:create|add)\s+(?:a\s+)?task\s+(?:to|about)\s+([^\"'\n.,]+?)(?:\s+assigned\s+to|$)",
                text,
                flags=re.IGNORECASE,
            )
        if task_match:
            cand = task_match.group(1).strip()
            if cand.lower() not in ("assigned", "assigned to", "for", "to"):
                task_summary = cand

        target_uid = None
        target_uname = None
        for en in employee_names:
            if en.startswith("U") and len(en) >= 8 and en[1:].isalnum():
                target_uid = en
                break
            elif not target_uname and en.lower() not in stopwords:
                target_uname = en

        return ExtractedEntities(
            employee_names=employee_names,
            target_user_id=target_uid or (employee_names[0] if employee_names and employee_names[0].startswith("U") else None),
            target_user_name=target_uname,
            dates=dates,
            times=times,
            duration_minutes=duration_minutes,
            event_title=event_title,
            task_summary=task_summary,
        )

    # ======================================================================
    # CLARIFICATION PROMPT GENERATION
    # ======================================================================

    @staticmethod
    def _generate_clarification_prompt(
        missing_fields: list[str],
        pending: PendingOperation | None = None,
        operation_type: str = "schedule",
        title: str | None = None,
    ) -> str:
        """
        Generate a concise, polite clarification prompt for missing required fields.
        """
        has_date = "date" in missing_fields or "dates" in missing_fields
        has_time = "time" in missing_fields or "times" in missing_fields
        has_title = "title" in missing_fields or "event_title" in missing_fields
        has_task = "task_summary" in missing_fields or "summary" in missing_fields

        if has_date and has_time:
            return "What date and time would you like to schedule this for?"
        if has_date:
            return "What date should I schedule this for?"
        if has_time:
            return "What time should I schedule this for?"
        if has_task:
            return "What is the description or summary for this task?"
        if has_title:
            return "What title should I give this meeting?"

        fields_str = ", ".join(missing_fields)
        return f"Could you please specify the following details: {fields_str}?"
