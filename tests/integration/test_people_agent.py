from application.cognitive import SimpleCognitiveEngine
from application.activity import ActivityQuestionService
from domain.activity import ActivityType
from domain.activity.aggregates.activity_event import ActivityEvent
from domain.activity.enums.activity_source import ActivitySource
from domain.reasoning import Answer, Question
from unittest.mock import Mock
from datetime import datetime, timezone


class FakeQuestionAnswering:
    def __init__(self):
        self.calls = []

    def retrieve_evidence(self, question):
        return []

    def answer_from_evidence(
        self,
        question,
        evidence,
        *,
        fallback_evidence=None,
    ):
        self.calls.append((question, evidence))
        return Answer(
            text="Akshat works on AI agent implementation.",
            confidence=0.8,
            evidence=evidence,
        )

    def answer(self, question):
        return Answer(
            text="Fallback answer.",
            confidence=0.0,
            evidence=[],
        )


class FakeKnowledgeRetrieval:
    def __init__(self):
        self.calls = []

    def retrieve(
        self,
        question,
        *,
        limit=5,
        employee_slack_user_id=None,
    ):
        self.calls.append({
            "question": question,
            "limit": limit,
            "employee_slack_user_id": employee_slack_user_id,
        })
        return [
            (
                Mock(
                    content="Akshat works on AI agent implementation.",
                    metadata={
                        "document_name": "Akshat_Work_Profile.docx",
                        "knowledge_type": "employee_profile",
                        "employee_slack_user_id": "U123",
                    },
                ),
                0.9,
            )
        ]


def test_people_profile_question_flows_through_cognitive_engine():
    question_answering = FakeQuestionAnswering()
    knowledge_retrieval = FakeKnowledgeRetrieval()

    engine = SimpleCognitiveEngine(
        pipeline=None,
        question_answering=question_answering,
        knowledge_base_retrieval_service=knowledge_retrieval,
    )

    answer = engine.ask(
        Question(
            text="What does Akshat work on?",
            target_user_id="U123",
            target_user_name="Akshat",
        )
    )

    assert answer.text == "Akshat works on AI agent implementation."
    assert len(knowledge_retrieval.calls) == 1
    assert (
        knowledge_retrieval.calls[0]["employee_slack_user_id"]
        == "U123"
    )
    assert "Akshat works on AI agent implementation." in answer.evidence[0]


def test_people_activity_question_flows_through_cognitive_engine():
    now = datetime(
        2026,
        10,
        8,
        10,
        0,
        tzinfo=timezone.utc,
    )

    event = ActivityEvent.create(
        person_id="U123",
        person_name="Akshat",
        activity_type=ActivityType.WORK_START,
        occurred_at=now,
        source=ActivitySource.SLACK,
        source_event_id="activity-1",
    )

    activity_service = Mock()
    activity_service.find_people_by_name.return_value = [event]
    activity_service.find_currently_working.return_value = [event]

    activity_questions = ActivityQuestionService(
        activity_service=activity_service,
        now_provider=lambda: now,
    )

    engine = SimpleCognitiveEngine(
        pipeline=None,
        question_answering=FakeQuestionAnswering(),
        activity_question_service=activity_questions,
    )

    answer = engine.ask(
        Question(text="Is Akshat working?")
    )

    assert answer is not None
    assert "Akshat" in answer.text
