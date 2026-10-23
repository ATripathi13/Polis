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


def test_people_agent_answers_from_recorded_activity_history():
    from application.activity import ActivityService, AttendanceCalculator

    class InMemoryActivityRepository:
        def __init__(self):
            self.events = []
            self.source_keys = set()

        def save(self, event):
            key = (event.person_id, event.source_event_id)
            if event.source_event_id is not None and key in self.source_keys:
                return
            if event.source_event_id is not None:
                self.source_keys.add(key)
            self.events.append(event)

        def find_for_person(self, person_id, *, start=None, end=None):
            events = [
                event for event in self.events
                if event.person_id == person_id
                and (start is None or event.occurred_at >= start)
                and (end is None or event.occurred_at <= end)
            ]
            return sorted(events, key=lambda event: event.occurred_at)

        def find_people_by_name(self, person_name):
            matches = [
                event for event in self.events
                if event.person_name.lower() == person_name.strip().lower()
            ]
            latest_by_person = {}
            for event in sorted(
                matches,
                key=lambda event: event.occurred_at,
                reverse=True,
            ):
                latest_by_person.setdefault(event.person_id, event)
            return list(latest_by_person.values())

        def find_currently_on_break(self):
            return [
                event for event in self._latest()
                if event.activity_type == ActivityType.BREAK_START
            ]

        def find_currently_working(self):
            return [
                event for event in self._latest()
                if event.activity_type in {
                    ActivityType.WORK_START,
                    ActivityType.BREAK_END,
                }
            ]

        def find_currently_off_work(self):
            return [
                event for event in self._latest()
                if event.activity_type == ActivityType.WORK_END
            ]

        def find_latest_for_people(self):
            return self._latest()

        def _latest(self):
            latest_by_person = {}
            for event in sorted(
                self.events,
                key=lambda event: event.occurred_at,
                reverse=True,
            ):
                latest_by_person.setdefault(event.person_id, event)
            return list(latest_by_person.values())

    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    repository = InMemoryActivityRepository()
    activity_service = ActivityService(
        repository=repository,
        attendance_calculator=AttendanceCalculator(),
    )

    activity_service.record(
        person_id="U123",
        person_name="Akshat",
        activity_type=ActivityType.WORK_START,
        occurred_at=now.replace(hour=9),
        source=ActivitySource.SLACK,
        source_event_id="slack-work-start",
    )
    activity_service.record(
        person_id="U123",
        person_name="Akshat",
        activity_type=ActivityType.BREAK_START,
        occurred_at=now.replace(hour=11),
        source=ActivitySource.SLACK,
        source_event_id="slack-break-start",
    )
    activity_service.record(
        person_id="U123",
        person_name="Akshat",
        activity_type=ActivityType.BREAK_START,
        occurred_at=now.replace(hour=11),
        source=ActivitySource.SLACK,
        source_event_id="slack-break-start",
    )

    assert len(repository.events) == 2

    activity_questions = ActivityQuestionService(
        activity_service=activity_service,
        now_provider=lambda: now,
    )
    engine = SimpleCognitiveEngine(
        pipeline=None,
        question_answering=FakeQuestionAnswering(),
        activity_question_service=activity_questions,
    )

    answer = engine.ask(Question(text="Is Akshat working?"))

    assert answer is not None
    assert answer.text == "Akshat is not currently working."

    break_answer = engine.ask(Question(text="Is Akshat on break?"))

    assert break_answer is not None
    assert break_answer.text == "Akshat is currently on break."
