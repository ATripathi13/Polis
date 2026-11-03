"""
Unit tests for ActivityDetector.

Verifies:
1. All existing explicit work-start, break-start, break-end, and work-end phrases still work.
2. Natural greetings in different casing and punctuation classify as WORK_START with is_greeting=True.
3. Compound greeting messages extract substantive query while classifying greeting prefix as WORK_START.
4. Greeting plus task/calendar request extract substantive query without losing original text.
5. Ordinary farewells never produce WORK_END (remain conversational only, returning None).
6. Explicit sign-offs produce WORK_END.
7. Unrelated questions and messages produce no lifecycle intent.
8. Original message content is always preserved in note.
9. Existing break detection remains unchanged.
"""

import pytest

from application.activity.activity_detector import ActivityDetector, DetectedActivity
from domain.activity import ActivityType


def test_detect_work_start():
    detector = ActivityDetector()
    for phrase in [
        "starting work",
        "starting my day",
        "i'm starting work",
        "im starting work",
        "beginning work",
        "starting now",
    ]:
        res = detector.detect(phrase)
        assert res is not None, f"Expected match for '{phrase}'"
        assert res.activity_type == ActivityType.WORK_START
        assert res.note == phrase
        assert res.is_greeting is False
        assert res.substantive_query is None


def test_detect_break_start():
    detector = ActivityDetector()
    for phrase in [
        "stepping away",
        "taking a break",
        "going on break",
        "stepping out for a bit",
        "going to lunch",
        "on lunch break",
    ]:
        res = detector.detect(phrase)
        assert res is not None, f"Expected match for '{phrase}'"
        assert res.activity_type == ActivityType.BREAK_START
        assert res.note == phrase
        assert res.is_greeting is False


def test_detect_break_end_back_to_work():
    """Verify 'back to work' and related phrases correctly classify as BREAK_END."""
    detector = ActivityDetector()
    for phrase in [
        "back to work",
        "i'm back to work",
        "im back to work",
        "i am back to work",
        "back at work",
        "back",
        "i'm back",
        "back from lunch",
        "back from break",
    ]:
        res = detector.detect(phrase)
        assert res is not None, f"Expected match for '{phrase}'"
        assert res.activity_type == ActivityType.BREAK_END, f"'{phrase}' should be BREAK_END, got {res.activity_type}"
        assert res.note == phrase
        assert res.is_greeting is False


def test_detect_work_end():
    detector = ActivityDetector()
    for phrase in [
        "done for today",
        "done for the day",
        "finished for today",
        "logging off",
        "signing off",
        "leaving work",
    ]:
        res = detector.detect(phrase)
        assert res is not None, f"Expected match for '{phrase}'"
        assert res.activity_type == ActivityType.WORK_END
        assert res.note == phrase
        assert res.is_greeting is False


def test_detect_natural_greetings_as_work_start():
    """Verify natural greetings in various casings and punctuation classify as WORK_START."""
    detector = ActivityDetector()
    greetings = [
        "Good morning",
        "good morning",
        "GOOD MORNING",
        "Good morning!",
        "Good morning.",
        "Good morning...",
        "Good afternoon",
        "good afternoon",
        "GOOD AFTERNOON",
        "Good afternoon!",
        "Good evening",
        "good evening",
        "Good evening!",
        "Morning",
        "morning",
        "MORNING",
        "Morning!",
        "Morning, team!",
        "Hi",
        "hi",
        "HI",
        "Hi!",
        "Hi.",
        "Hello",
        "hello",
        "HELLO",
        "Hello!",
        "Hey",
        "hey",
        "HEY",
        "Hey!",
        "Hi team",
        "hi team",
        "HI TEAM",
        "Hi team!",
        "Hello everyone",
        "hello everyone",
        "HELLO EVERYONE",
        "Hello everyone!",
        "Hey everyone",
        "hey everyone",
        "HEY EVERYONE",
        "Hey everyone!",
        "Good morning team",
        "Good morning team!",
        "Good morning everyone",
        "Morning team",
        "Morning everyone",
        "Hey team",
        "Hey team!",
    ]
    for phrase in greetings:
        res = detector.detect(phrase)
        assert res is not None, f"Expected match for greeting: '{phrase}'"
        assert res.activity_type == ActivityType.WORK_START, f"Expected WORK_START for '{phrase}'"
        assert res.is_greeting is True
        assert res.substantive_query is None, f"Expected no substantive query for '{phrase}', got '{res.substantive_query}'"
        assert res.note == phrase


def test_detect_compound_greeting_with_substantive_question():
    """Verify greeting prefix triggers WORK_START and extracts substantive query."""
    detector = ActivityDetector()
    compound_questions = [
        (
            "Good morning! Can you check the roadmap?",
            "Can you check the roadmap?",
        ),
        (
            "Hi POLIS, what is the status of my tasks?",
            "what is the status of my tasks?",
        ),
        (
            "Hello, what are my open action items?",
            "what are my open action items?",
        ),
        (
            "Morning team, who is handling the deploy today?",
            "who is handling the deploy today?",
        ),
        (
            "Hey, when does the quarterly review start?",
            "when does the quarterly review start?",
        ),
        (
            "Good afternoon! How are we tracking on sprint goals?",
            "How are we tracking on sprint goals?",
        ),
        (
            "Good evening team - update on the release?",
            "update on the release?",
        ),
    ]
    for phrase, expected_query in compound_questions:
        res = detector.detect(phrase)
        assert res is not None, f"Expected match for compound greeting: '{phrase}'"
        assert res.activity_type == ActivityType.WORK_START
        assert res.is_greeting is True
        assert res.has_substantive_query is True
        assert res.substantive_query == expected_query, f"Expected query '{expected_query}', got '{res.substantive_query}'"
        assert res.note == phrase


def test_detect_compound_greeting_with_task_or_calendar_request():
    """Verify greeting plus action requests (task, calendar, reminder) classify correctly."""
    detector = ActivityDetector()
    compound_actions = [
        (
            "Hello team, schedule a meeting for tomorrow.",
            "schedule a meeting for tomorrow.",
        ),
        (
            "Good morning, remind me to submit expenses at 5pm",
            "remind me to submit expenses at 5pm",
        ),
        (
            "Hey POLIS, create a task to review Q3 roadmap",
            "create a task to review Q3 roadmap",
        ),
        (
            "<@U0BOT12345> Good morning! Can you schedule a sync with Bob?",
            "Can you schedule a sync with Bob?",
        ),
        (
            "@POLIS Hi team, schedule a sprint retrospective for Friday",
            "schedule a sprint retrospective for Friday",
        ),
    ]
    for phrase, expected_action in compound_actions:
        res = detector.detect(phrase)
        assert res is not None, f"Expected match for greeting action: '{phrase}'"
        assert res.activity_type == ActivityType.WORK_START
        assert res.is_greeting is True
        assert res.has_substantive_query is True
        assert res.substantive_query == expected_action
        assert res.note == phrase


def test_ordinary_farewells_never_produce_work_end():
    """Verify ordinary farewells remain conversational only and return None."""
    detector = ActivityDetector()
    farewells = [
        "Bye",
        "bye",
        "BYE",
        "Bye!",
        "Goodbye",
        "goodbye",
        "GOODBYE",
        "Goodbye!",
        "Goodbye everyone",
        "Goodbye team",
        "See ya",
        "see ya",
        "SEE YA",
        "See ya!",
        "See ya team",
        "Talk later",
        "talk later",
        "TALK LATER",
        "Talk later!",
        "See you tomorrow",
        "see you tomorrow",
        "SEE YOU TOMORROW",
        "See you tomorrow!",
        "See you later",
        "Bye for now",
        "Good night",
        "goodnight",
        "Goodnight everyone",
    ]
    for phrase in farewells:
        res = detector.detect(phrase)
        assert res is None, f"Ordinary farewell '{phrase}' must return None, but got {res}"


def test_explicit_sign_offs_produce_work_end():
    """Verify explicit sign-off phrases produce WORK_END."""
    detector = ActivityDetector()
    sign_offs = [
        "Signing off for today",
        "signing off for today",
        "Signing off for today!",
        "Done for the day",
        "done for the day",
        "Done for the day.",
        "Logging off",
        "logging off",
        "Logging off!",
        "Finished work",
        "finished work",
        "Finished work.",
        "done for today",
        "finished for today",
        "signing off",
        "signing off now",
        "logging off now",
        "leaving work",
        "stopping work",
        "logging out",
        "i'm done for today",
        "i am done for the day",
        "i'm signing off for today",
        "i'm signing off for the day",
    ]
    for phrase in sign_offs:
        res = detector.detect(phrase)
        assert res is not None, f"Expected match for explicit sign-off: '{phrase}'"
        assert res.activity_type == ActivityType.WORK_END, f"Expected WORK_END for '{phrase}', got {res.activity_type}"
        assert res.is_greeting is False
        assert res.substantive_query is None
        assert res.note == phrase


def test_unrelated_questions_and_messages_produce_no_intent():
    """Verify non-lifecycle messages and questions do not trigger activity events."""
    detector = ActivityDetector()
    unrelated = [
        "What is a good morning routine?",
        "Can you check the roadmap?",
        "Schedule a meeting for tomorrow.",
        "What is the status of my tasks?",
        "This morning I saw a bug in production",
        "Say hello to Bob for me",
        "History of polis",
        "High priority item needing review",
        "Who is currently working?",
        "Is Alice on break?",
        "When did Bob start work?",
        "How are expenses reimbursed?",
        "The project deadline is Friday",
        "Help me with this report",
        "Highway traffic was bad today",
        "random non-activity conversation",
        "",
        "   ",
    ]
    for phrase in unrelated:
        res = detector.detect(phrase)
        assert res is None, f"Unrelated message '{phrase}' must return None, but got {res}"


def test_original_message_content_preserved_in_note():
    """Verify res.note matches the original raw text exactly without stripping or mutating."""
    detector = ActivityDetector()
    test_cases = [
        "  Good morning! Can you check the roadmap?  ",
        "Hi POLIS, what is the status of my tasks?",
        "  starting work  ",
        "  taking a break  ",
        "  back to work  ",
        "  signing off for today  ",
    ]
    for phrase in test_cases:
        res = detector.detect(phrase)
        assert res is not None
        assert res.note == phrase


def test_classify_alias_behavior():
    """Verify classify() method acts as a drop-in alias for detect()."""
    detector = ActivityDetector()
    assert detector.classify("Good morning") == detector.detect("Good morning")
    assert detector.classify("done for today") == detector.detect("done for today")
    assert detector.classify("Bye") is None
