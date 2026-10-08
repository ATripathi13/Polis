from application.cognitive import SimpleCognitiveEngine
from domain.reasoning import Answer, Question


class FakeQuestionAnswering:
    def retrieve_evidence(self, question):
        return []

    def answer_from_evidence(self, question, evidence, *, fallback_evidence=None):
        return Answer(
            text="The deployment report needs to be prepared.",
            confidence=0.8,
            evidence=evidence,
        )

    def answer(self, question):
        return Answer(
            text="Fallback answer.",
            confidence=0.0,
            evidence=[],
        )


class FakeOperationalItemService:
    def retrieve_evidence(self, question):
        if "task" in question.text.lower():
            return [
                "Operational item: task\n"
                "Summary: Prepare the deployment report\n"
                "Status: open\n"
                "Priority: medium"
            ]
        return []


def test_cognitive_engine_answers_from_operational_evidence():
    engine = SimpleCognitiveEngine(
        pipeline=None,
        question_answering=FakeQuestionAnswering(),
        operational_item_service=FakeOperationalItemService(),
    )

    answer = engine.ask(
        Question(text="What task needs to be completed?")
    )

    assert answer.text == (
        "The deployment report needs to be prepared."
    )
    assert len(answer.evidence) == 1
    assert "Prepare the deployment report" in answer.evidence[0]
