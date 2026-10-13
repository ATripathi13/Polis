"""
Knowledge Agent Specialist capability for POLIS.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from domain.knowledge.enums import KnowledgeStatus
from domain.knowledge.repositories import KnowledgeRepository
from domain.knowledge.value_objects import (
    KnowledgeCandidate,
    KnowledgeContradiction,
    KnowledgeResult,
    KnowledgeSourceReference,
    KnowledgeSubject,
)
from domain.organization import (
    OrganizationEvent,
    OrganizationEventType,
)
from domain.reasoning.value_objects import Question, Answer

logger = logging.getLogger(__name__)


class KnowledgeAgent:
    """
    Production-grade Knowledge Specialist Agent for POLIS.

    Coordinates knowledge retrieval, evidence-grounded reasoning, authority
    evaluation, contradiction handling, gap detection, and organizational
    knowledge lifecycle events.
    """

    def __init__(
        self,
        knowledge_repository: KnowledgeRepository,
        retrieval_service=None,
        answer_service=None,
        llm_client=None,
        organization_event_repository=None,
    ) -> None:
        self._knowledge_repository = knowledge_repository
        self._retrieval_service = retrieval_service
        self._answer_service = answer_service
        self._llm_client = llm_client
        self._organization_event_repository = organization_event_repository

    # =========================================================================
    # KNOWLEDGE RETRIEVAL & GROUNDED ANSWERING
    # =========================================================================

    def ask(
        self,
        question: Question | str,
        *,
        employee_slack_user_id: str | None = None,
        limit: int = 5,
    ) -> KnowledgeResult:
        """
        Answer a question using grounded organizational knowledge.

        Evaluates evidence, checks for contradictions and knowledge gaps,
        and returns a structured KnowledgeResult.
        """
        question_text = (
            question.text if isinstance(question, Question) else str(question)
        ).strip()

        if not question_text:
            return KnowledgeResult(
                status=KnowledgeStatus.MISSING,
                answer="Please provide a question.",
                confidence=0.0,
                evidence=[],
                sources=[],
                missing_aspects=["empty_question"],
            )

        target_user = (
            employee_slack_user_id
            if employee_slack_user_id is not None
            else (
                question.target_user_id
                if isinstance(question, Question)
                else None
            )
        )

        kb_chunks = []
        if self._retrieval_service is not None:
            try:
                kb_chunks = self._retrieval_service.retrieve(
                    question_text,
                    limit=limit,
                    employee_slack_user_id=target_user,
                )
            except Exception as e:
                logger.warning("Error retrieving from knowledge base: %s", e)
                kb_chunks = []

        domain_candidates = self._find_matching_domain_knowledge(question_text)

        evidence_list: list[str] = []
        sources_list: list[KnowledgeSourceReference] = []

        for chunk, score in kb_chunks:
            content = chunk.content.strip()
            if not content:
                continue
            doc_name = chunk.metadata.get("document_name", "Unknown")
            authority = chunk.metadata.get("authority")
            evidence_str = (
                f"Knowledge Base document: {doc_name} (Score: {score:.2f})\n{content}"
            )
            evidence_list.append(evidence_str)
            sources_list.append(
                KnowledgeSourceReference(
                    source_type="knowledge_base",
                    document_name=doc_name,
                    authority=authority if isinstance(authority, str) else None,
                    snippet=content[:200],
                )
            )

        for cand in domain_candidates:
            cand_evidence = f"Organizational Knowledge: {cand.subject.identifier}\n{cand.summary}"
            evidence_list.append(cand_evidence)
            sources_list.append(
                KnowledgeSourceReference(
                    source_type="domain_knowledge",
                    document_name=cand.subject.identifier,
                    snippet=cand.summary[:200],
                )
            )

        if not evidence_list:
            return KnowledgeResult(
                status=KnowledgeStatus.MISSING,
                answer="I couldn't find relevant information in the Knowledge Base.",
                confidence=0.0,
                evidence=[],
                sources=[],
                missing_aspects=[question_text],
            )

        contradiction = self._detect_evidence_contradictions(
            question_text, kb_chunks, domain_candidates
        )
        if contradiction is not None:
            return KnowledgeResult(
                status=KnowledgeStatus.CONFLICTING,
                answer=(
                    f"Conflicting knowledge detected: {contradiction.conflict_explanation} "
                    f"Existing: '{contradiction.existing_knowledge}'. "
                    f"Conflicting: '{contradiction.new_knowledge}'."
                ),
                confidence=0.4,
                evidence=evidence_list,
                sources=sources_list,
                contradictions=[contradiction],
            )

        uncertainty_aspects = self._detect_knowledge_gaps(
            question_text, evidence_list
        )
        if uncertainty_aspects:
            grounded_answer = self._generate_answer(
                question_text, kb_chunks, evidence_list
            )
            return KnowledgeResult(
                status=KnowledgeStatus.UNCERTAIN,
                answer=grounded_answer.text,
                confidence=min(grounded_answer.confidence, 0.5),
                evidence=evidence_list,
                sources=sources_list,
                missing_aspects=uncertainty_aspects,
            )

        grounded_answer = self._generate_answer(
            question_text, kb_chunks, evidence_list
        )

        status = (
            KnowledgeStatus.KNOWN
            if grounded_answer.confidence > 0.0
            else KnowledgeStatus.UNCERTAIN
        )

        return KnowledgeResult(
            status=status,
            answer=grounded_answer.text,
            confidence=grounded_answer.confidence,
            evidence=evidence_list,
            sources=sources_list,
        )

    def retrieve_evidence(
        self,
        question: Question | str,
        *,
        limit: int = 5,
    ) -> list[str]:
        """
        Retrieve formatted knowledge evidence strings for POLIS unified answering.
        """
        question_text = (
            question.text if isinstance(question, Question) else str(question)
        ).strip()

        if not question_text:
            return []

        result = self.ask(question_text, limit=limit)
        return result.evidence

    # =========================================================================
    # EVENT HANDLING
    # =========================================================================

    def process_event(
        self,
        event: OrganizationEvent,
        *,
        source_type: str = "",
        source_event_id: str = "",
        persist: bool = True,
    ) -> KnowledgeResult | None:
        """
        Process canonical organization events relevant to knowledge intelligence.
        """
        if event.event_type == OrganizationEventType.KNOWLEDGE_DISCOVERED:
            return self._handle_knowledge_discovered(
                event, source_type=source_type, source_event_id=source_event_id, persist=persist
            )

        if event.event_type == OrganizationEventType.KNOWLEDGE_UPDATED:
            return self._handle_knowledge_updated(
                event, source_type=source_type, source_event_id=source_event_id, persist=persist
            )

        if event.event_type == OrganizationEventType.CONTRADICTION_DETECTED:
            return self._handle_contradiction_detected(
                event, source_type=source_type, source_event_id=source_event_id
            )

        if event.event_type == OrganizationEventType.QUESTION_ASKED:
            return self.ask(event.summary)

        return None

    # =========================================================================
    # SPECIALIZED EVENT HANDLERS
    # =========================================================================

    def _handle_knowledge_discovered(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
        persist: bool = True,
    ) -> KnowledgeResult:
        """
        Handle KNOWLEDGE_DISCOVERED event.

        Evaluates whether this represents genuinely new knowledge, an idempotent
        duplicate, or already covered knowledge.
        """
        subject_id = self._extract_subject_identifier(event)
        summary = event.summary.strip()

        existing = self._knowledge_repository.find(subject_id)
        if existing is not None:
            if existing.summary.strip().lower() == summary.lower():
                return KnowledgeResult(
                    status=KnowledgeStatus.KNOWN,
                    answer=f"Knowledge already known: {existing.summary}",
                    confidence=1.0,
                    evidence=[
                        ev
                        for obs in event.observations
                        for ev in obs.evidence
                        if ev
                    ],
                    sources=[
                        KnowledgeSourceReference(
                            source_type=source_type or "event",
                            source_event_id=source_event_id,
                            document_name=subject_id,
                            snippet=existing.summary,
                        )
                    ],
                    knowledge_changes=[],
                )

        candidate = KnowledgeCandidate(
            subject=KnowledgeSubject(
                kind="discovered",
                identifier=subject_id,
            ),
            summary=summary,
            supporting_events=[event],
            confidence=event.confidence,
        )

        if persist:
            self._knowledge_repository.save(candidate)

        evidence_items = [
            ev
            for obs in event.observations
            for ev in obs.evidence
            if ev
        ] or [summary]

        return KnowledgeResult(
            status=KnowledgeStatus.KNOWN,
            answer=f"Discovered new knowledge: {summary}",
            confidence=event.confidence,
            evidence=evidence_items,
            sources=[
                KnowledgeSourceReference(
                    source_type=source_type or "event",
                    source_event_id=source_event_id,
                    document_name=subject_id,
                    snippet=summary,
                )
            ],
            knowledge_changes=[
                {
                    "action": "discovered",
                    "subject": subject_id,
                    "summary": summary,
                    "confidence": event.confidence,
                }
            ],
        )

    def _handle_knowledge_updated(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
        persist: bool = True,
    ) -> KnowledgeResult:
        """
        Handle KNOWLEDGE_UPDATED event.

        Evaluates previous knowledge, verifies authority, and prevents silent
        overwrites of authoritative knowledge by lower-authority sources.
        """
        subject_id = self._extract_subject_identifier(event)
        summary = event.summary.strip()
        existing = self._knowledge_repository.find(subject_id)

        incoming_authority = self._extract_event_authority(event)

        if existing is not None:
            if existing.summary.strip().lower() == summary.lower():
                return KnowledgeResult(
                    status=KnowledgeStatus.KNOWN,
                    answer=f"Knowledge already up-to-date: {summary}",
                    confidence=1.0,
                    evidence=[
                        ev
                        for obs in event.observations
                        for ev in obs.evidence
                        if ev
                    ],
                    sources=[
                        KnowledgeSourceReference(
                            source_type=source_type or "event",
                            source_event_id=source_event_id,
                            document_name=subject_id,
                            authority=incoming_authority,
                            snippet=summary,
                        )
                    ],
                    knowledge_changes=[],
                )

            if incoming_authority == "unverified" or (
                hasattr(existing, "confidence") and existing.confidence > 0.9 and event.confidence < 0.5
            ):
                contradiction = KnowledgeContradiction(
                    existing_knowledge=existing.summary,
                    new_knowledge=summary,
                    conflict_explanation="Incoming update lacks necessary authority to supersede existing knowledge.",
                    supporting_evidence=[
                        ev
                        for obs in event.observations
                        for ev in obs.evidence
                        if ev
                    ],
                    authority_info={
                        "existing_authority": "authoritative",
                        "incoming_authority": incoming_authority,
                    },
                    recommended_resolution="escalate",
                )
                return KnowledgeResult(
                    status=KnowledgeStatus.CONFLICTING,
                    answer=(
                        f"Cannot update '{subject_id}': incoming update conflicts with "
                        f"existing authoritative knowledge."
                    ),
                    confidence=event.confidence,
                    evidence=[
                        ev
                        for obs in event.observations
                        for ev in obs.evidence
                        if ev
                    ],
                    sources=[
                        KnowledgeSourceReference(
                            source_type=source_type or "event",
                            source_event_id=source_event_id,
                            document_name=subject_id,
                            authority=incoming_authority,
                            snippet=summary,
                        )
                    ],
                    contradictions=[contradiction],
                )

            prev_summary = existing.summary
        else:
            prev_summary = None

        candidate = KnowledgeCandidate(
            subject=KnowledgeSubject(
                kind="updated",
                identifier=subject_id,
            ),
            summary=summary,
            supporting_events=[event],
            confidence=event.confidence,
        )

        if persist:
            self._knowledge_repository.save(candidate)

        evidence_items = [
            ev
            for obs in event.observations
            for ev in obs.evidence
            if ev
        ] or [summary]

        return KnowledgeResult(
            status=KnowledgeStatus.UPDATED,
            answer=f"Updated knowledge: {summary}",
            confidence=event.confidence,
            evidence=evidence_items,
            sources=[
                KnowledgeSourceReference(
                    source_type=source_type or "event",
                    source_event_id=source_event_id,
                    document_name=subject_id,
                    authority=incoming_authority,
                    snippet=summary,
                )
            ],
            knowledge_changes=[
                {
                    "action": "updated",
                    "subject": subject_id,
                    "previous_summary": prev_summary,
                    "new_summary": summary,
                    "confidence": event.confidence,
                }
            ],
        )

    def _handle_contradiction_detected(
        self,
        event: OrganizationEvent,
        *,
        source_type: str,
        source_event_id: str,
    ) -> KnowledgeResult:
        """
        Handle CONTRADICTION_DETECTED event.

        Produces structured contradiction intelligence without destroying
        authoritative knowledge.
        """
        summary = event.summary.strip()
        evidence_items = [
            ev
            for obs in event.observations
            for ev in obs.evidence
            if ev
        ]

        existing_text = ""
        new_text = summary
        explanation = "Direct conflict detected between organizational information sources."

        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            if "existing_knowledge" in meta:
                existing_text = str(meta["existing_knowledge"])
            if "new_knowledge" in meta:
                new_text = str(meta["new_knowledge"])
            if "conflict_explanation" in meta:
                explanation = str(meta["conflict_explanation"])

        if not existing_text:
            match = re.search(r"conflicts with ['\"]?([^'\"]+)['\"]?", summary, re.IGNORECASE)
            if match:
                existing_text = match.group(1).strip()
            else:
                existing_text = "Prior authoritative baseline"

        contradiction = KnowledgeContradiction(
            existing_knowledge=existing_text,
            new_knowledge=new_text,
            conflict_explanation=explanation,
            supporting_evidence=evidence_items,
            authority_info={
                "source_type": source_type or "event",
                "source_event_id": source_event_id,
            },
            recommended_resolution="escalate",
        )

        return KnowledgeResult(
            status=KnowledgeStatus.CONFLICTING,
            answer=f"Contradiction identified: {summary}",
            confidence=event.confidence,
            evidence=evidence_items,
            sources=[
                KnowledgeSourceReference(
                    source_type=source_type or "event",
                    source_event_id=source_event_id,
                    snippet=summary,
                )
            ],
            contradictions=[contradiction],
        )

    # =========================================================================
    # KNOWLEDGE REASONING & EVIDENCE UTILITIES
    # =========================================================================

    def _find_matching_domain_knowledge(
        self, query: str
    ) -> list[KnowledgeCandidate]:
        """
        Find matching candidates from the structured knowledge repository.
        """
        try:
            all_records = self._knowledge_repository.all()
        except Exception as e:
            logger.warning("Error querying knowledge repository: %s", e)
            return []

        STOP_WORDS = {
            "a", "an", "the", "in", "on", "at", "to", "for", "of", "and",
            "is", "are", "was", "were", "do", "does", "did", "what", "which",
            "who", "how", "when", "where", "why", "we", "our", "us", "you",
            "your", "it", "its", "they", "them", "their", "this", "that", "these", "those",
        }
        tokens = {t for t in re.findall(r"\w+", query.lower()) if t not in STOP_WORDS}
        if not tokens:
            return []

        matched = []

        for record in all_records:
            record_text = f"{record.subject.identifier} {record.summary}".lower()
            record_tokens = {t for t in re.findall(r"\w+", record_text) if t not in STOP_WORDS}
            overlap = tokens.intersection(record_tokens)
            if overlap:
                matched.append(record)

        return matched

    def _detect_evidence_contradictions(
        self,
        query: str,
        kb_chunks: list,
        domain_candidates: list[KnowledgeCandidate],
    ) -> KnowledgeContradiction | None:
        """
        Detect whether retrieved evidence contains opposing facts or contradictions.
        """
        texts = [chunk.content for chunk, _score in kb_chunks] + [
            cand.summary for cand in domain_candidates
        ]
        if len(texts) < 2:
            return None

        # Check for explicit contradiction indicators in retrieved sources
        for i, text1 in enumerate(texts):
            lower1 = text1.lower()
            for j in range(i + 1, len(texts)):
                lower2 = texts[j].lower()

                # Rule 1: Negation conflict (e.g. "is required" vs "is not required")
                for key_term in ["required", "mandatory", "deprecated", "enabled", "disabled", "allowed", "prohibited"]:
                    if f"is {key_term}" in lower1 and f"not {key_term}" in lower2:
                        return KnowledgeContradiction(
                            existing_knowledge=text1,
                            new_knowledge=texts[j],
                            conflict_explanation=f"Conflicting statements regarding whether {key_term} is applicable.",
                            supporting_evidence=[text1, texts[j]],
                            recommended_resolution="escalate",
                        )
                    if f"is {key_term}" in lower2 and f"not {key_term}" in lower1:
                        return KnowledgeContradiction(
                            existing_knowledge=texts[j],
                            new_knowledge=text1,
                            conflict_explanation=f"Conflicting statements regarding whether {key_term} is applicable.",
                            supporting_evidence=[texts[j], text1],
                            recommended_resolution="escalate",
                        )

        return None

    def _detect_knowledge_gaps(
        self, query: str, evidence: list[str]
    ) -> list[str]:
        """
        Detect if evidence is partial or expresses explicit uncertainty.
        """
        gaps = []
        combined = " ".join(evidence).lower()
        if any(
            phrase in combined
            for phrase in [
                "tentative",
                "to be decided",
                "tbd",
                "unconfirmed",
                "uncertain",
                "preliminary",
                "unresolved",
            ]
        ):
            gaps.append("Information is marked as tentative or unconfirmed.")

        return gaps

    def _generate_answer(
        self,
        query: str,
        kb_chunks: list,
        evidence: list[str],
    ) -> Answer:
        """
        Generate grounded answer utilizing existing KnowledgeBaseAnswerService or LLM.
        """
        if self._answer_service is not None and kb_chunks:
            return self._answer_service.answer(query, kb_chunks)

        if self._llm_client is not None and evidence:
            context = "\n\n".join(evidence[:5])
            prompt = (
                f"You are POLIS, an organizational knowledge assistant.\n"
                f"Answer the user's question using ONLY the evidence provided below.\n\n"
                f"Question: {query}\n\n"
                f"Evidence:\n{context}\n\n"
                f"Instructions:\n"
                f"- Answer concisely and factually.\n"
                f"- If evidence does not provide enough info, say so clearly.\n"
                f"- Do not assume or hallucinate."
            )
            try:
                response = self._llm_client.generate(prompt)
                if response and response.strip():
                    return Answer(
                        text=response.strip(),
                        confidence=0.8,
                        evidence=evidence,
                    )
            except Exception as e:
                logger.warning("LLM answer generation failed: %s", e)

        # Fallback to direct evidence synthesis
        if evidence:
            first_line = evidence[0].split("\n")[-1]
            return Answer(
                text=first_line,
                confidence=0.7,
                evidence=evidence,
            )

        return Answer(
            text="POLIS does not have enough information to answer that question.",
            confidence=0.0,
            evidence=[],
        )

    def _extract_subject_identifier(self, event: OrganizationEvent) -> str:
        """
        Extract canonical subject identifier from an organization event.
        """
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            if "subject" in meta and meta["subject"]:
                return str(meta["subject"]).strip().lower()

        tokens = re.findall(r"\w+", event.summary.lower())
        if tokens:
            return "_".join(tokens[:5])
        return "general_knowledge"

    def _extract_event_authority(self, event: OrganizationEvent) -> str:
        """
        Extract authority level from event metadata if present.
        """
        for obs in event.observations:
            meta = getattr(obs, "metadata", {}) or {}
            if "authority" in meta and meta["authority"]:
                return str(meta["authority"]).strip()
        return "standard"

    def get_known_knowledge(
        self,
        topic: str | None = None,
        limit: int = 20,
    ) -> list[KnowledgeCandidate]:
        """
        Return stored authoritative knowledge records.
        """
        try:
            records = self._knowledge_repository.all()
        except Exception as e:
            logger.warning("Error fetching known knowledge: %s", e)
            return []

        if topic:
            tokens = set(re.findall(r"\w+", topic.lower()))
            filtered = [
                r
                for r in records
                if tokens.intersection(
                    set(re.findall(r"\w+", f"{r.subject.identifier} {r.summary}".lower()))
                )
            ]
            return filtered[:limit]

        return records[:limit]
