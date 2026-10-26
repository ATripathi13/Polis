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
            (
                f"Source {index}\n"
                f"Document: {chunk.metadata.get('document_name', 'Unknown')}\n"
                f"Content:\n{chunk.content}"
            )
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
- Speak naturally in the first person as a helpful, thoughtful teammate (using "I", "I'll", "I've", "don't", "can't").
- Use simple, familiar everyday English instead of corporate or technical jargon.
- Prefer short, clear sentences.
- Answer the user's question directly without unnecessary introductions, preamble, or repetitive greetings.
- Sound friendly, calm, confident, and professional without sounding stiff or robotic.
- Do not overuse "I" — use it naturally, not in every sentence.
- Use only the provided Knowledge Base content.
- When a source is an employee profile document and its document name identifies the employee, use that document identity to associate the profile information with that employee. Do not add facts that are not present in the profile.
- Do not invent or assume facts.
- Do not use general world knowledge.
- If the provided content does not contain enough information to answer confidently, clearly say so in plain first person (e.g., "I don't have enough information in the knowledge base to answer that confidently.").
- Do not mention embeddings, vector search, retrieval, databases, internal systems, or model behavior.
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