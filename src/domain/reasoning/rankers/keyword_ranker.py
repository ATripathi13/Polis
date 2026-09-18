"""
Keyword-based knowledge ranking.
"""

from __future__ import annotations

from domain.knowledge import (
    KnowledgeCandidate,
)

from domain.reasoning.value_objects.question import (
    Question,
)

from .knowledge_ranker import (
    KnowledgeRanker,
)

import re

class KeywordRanker(
    KnowledgeRanker,
):
    """
    Ranks knowledge candidates using
    simple keyword overlap.
    """
    _STOP_WORDS = {
        "a",
        "an",
        "are",
        "at",
        "do",
        "does",
        "did",
        "for",
        "how",
        "in",
        "is",
        "of",
        "on",
        "our",
        "the",
        "to",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
    }
    def _tokenize(
        self,
        text: str,
    ) -> set[str]:
        """
        Normalize text into searchable keywords.
        """

        return {
            word for word in re.findall(
                r"[a-z0-9]+",
                text.lower(),
            )
            if word not in self._STOP_WORDS
        }

    def best_match(
        self,
        question: Question,
        knowledge: list[KnowledgeCandidate],
    ) -> KnowledgeCandidate | None:
        if not knowledge:
            return None
        conversation_text = question.text

        if question.context is not None:
            conversation_text = " ".join(
                message["content"]
                for message in question.context.history
                if message.get("content")
            ) + " " + question.text

        question_words = self._tokenize(
            conversation_text,
        )
        
        best_candidate = None

        best_score = -1

        for candidate in knowledge:
            candidate_words = self._tokenize(
                candidate.summary,
            )
            subject_words = self._tokenize(
                candidate.subject.identifier,
            )
            summary_score = len(
                question_words.intersection(
                    candidate_words,
                )
            )

            subject_score = len(
                question_words.intersection(
                    subject_words,
                )
            )

            score = summary_score + (subject_score * 2)
            print(
                f"[RANKER] "
                f"{candidate.summary!r} "
                f"summary={summary_score} "
                f"subject={subject_score} "
                f"total={score}"
            )
            if score > best_score:

                best_score = score

                best_candidate = candidate

        if best_score <= 0:
            return None
        print(
            "[RANKER] BEST:",
            best_candidate.summary if best_candidate else None,
        )
        return best_candidate