from __future__ import annotations

from domain.reasoning.value_objects import Answer

from infrastructure.llm import OpenRouterClient


class KnowledgeBaseAnswerService:
    """
    Generates grounded answers using retrieved Knowledge Base chunks.
    """

    def __init__(
        self,
        *,
        llm_client: OpenRouterClient,
    ) -> None:
        self._llm_client = llm_client

    def answer(
        self,
        question: str,
        results,
    ) -> Answer:
        """
        Answer using only the retrieved Knowledge Base content.
        """

        if not question.strip():
            return Answer(
                text="Please provide a question.",
                confidence=0.0,
                evidence=[],
            )

        if not results:
            return Answer(
                text=(
                    "I couldn't find relevant information "
                    "in the Knowledge Base."
                ),
                confidence=0.0,
                evidence=[],
            )

        context = "\n\n".join(
            f"Source {index}:\n{chunk.content}"
            for index, (chunk, _score) in enumerate(
                results,
                start=1,
            )
        )

        prompt = f"""
You are POLIS, an organizational knowledge assistant.

Answer the user's question using ONLY the Knowledge Base
content provided below.

User question:
{question}

Knowledge Base content:
{context}

Instructions:
- Answer the question directly.
- Use only the provided Knowledge Base content.
- Do not invent or assume facts.
- Do not use general world knowledge.
- If the provided content does not contain enough information,
  clearly say that the Knowledge Base does not contain enough
  information to answer.
- Do not mention embeddings, vector search, retrieval,
  databases, internal systems, or model behavior.
- Keep the answer concise and natural.
- Return ONLY the answer.
""".strip()

        try:
            answer_text = self._llm_client.generate(
                prompt
            )
        except Exception:
            answer_text = ""

        if not answer_text.strip():
            return Answer(
                text=(
                    "I found relevant Knowledge Base information, "
                    "but I couldn't generate a reliable answer."
                ),
                confidence=0.0,
                evidence=[
                    chunk.content
                    for chunk, _score in results
                ],
            )

        evidence = [
            chunk.content
            for chunk, _score in results
        ]

        return Answer(
            text=answer_text.strip(),
            confidence=0.8,
            evidence=evidence,
        )