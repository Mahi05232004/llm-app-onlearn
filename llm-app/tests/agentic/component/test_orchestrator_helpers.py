"""Tests for orchestrator helpers — pure helper functions extracted from orchestrator.py."""

import pytest


class TestBuildThreadId:
    """_build_thread_id() should produce per-session thread IDs."""

    def test_basic(self):
        from app.api.endpoints.orchestrator import _build_thread_id

        assert _build_thread_id("dsa", "sess_123") == "dsa_sess_123"

    def test_ds_module(self):
        from app.api.endpoints.orchestrator import _build_thread_id

        assert _build_thread_id("ds", "abc") == "ds_abc"


class TestBuildConfig:
    """_build_config() should include all required configurable keys."""

    def test_all_keys_present(self):
        from app.api.endpoints.orchestrator import _build_config

        config = _build_config("dsa_sess_123", "user_abc", "dsa")

        assert config["configurable"]["thread_id"] == "dsa_sess_123"
        assert config["configurable"]["assistant_id"] == "user_abc"
        assert config["configurable"]["module"] == "dsa"
        assert config["recursion_limit"] == 100

    def test_ds_module(self):
        from app.api.endpoints.orchestrator import _build_config

        config = _build_config("ds_sess_456", "user_xyz", "ds")
        assert config["configurable"]["module"] == "ds"


class TestBuildTutorContext:
    """_build_tutor_context() should build the tutor_context dict."""

    def test_basic_context(self):
        from app.api.endpoints.orchestrator import _build_tutor_context

        ctx = _build_tutor_context(
            mode="learn",
            module="dsa",
            question_data={"question_title": "Two Sum"},
            code_context=None,
        )

        assert ctx["mode"] == "learn"
        assert ctx["module"] == "dsa"
        assert ctx["question_data"]["question_title"] == "Two Sum"
        assert ctx["code_context"] is None
        assert ctx["last_interaction_at"] is None

    def test_with_code_context(self):
        from app.api.endpoints.orchestrator import _build_tutor_context

        code = {"labCode": "def foo(): pass", "language": "python"}
        ctx = _build_tutor_context(
            mode="code",
            module="ds",
            question_data=None,
            code_context=code,
        )

        assert ctx["mode"] == "code"
        assert ctx["code_context"] == code

    def test_with_last_interaction(self):
        from app.api.endpoints.orchestrator import _build_tutor_context
        from datetime import datetime, timezone

        ts = datetime(2026, 2, 28, 12, 0, 0, tzinfo=timezone.utc)
        ctx = _build_tutor_context(
            mode="learn", module="dsa",
            question_data=None, code_context=None,
            last_interaction_at=ts,
        )

        assert ctx["last_interaction_at"] == ts


class TestExtractTopicId:
    """_extract_topic_id() should extract topicId from request files."""

    def test_extracts_from_topic_json(self):
        from app.api.endpoints.orchestrator import _extract_topic_id

        files = {"/topic.json": {"content": '{"topic_id": "q_1_2_3"}'}}
        assert _extract_topic_id(files) == "q_1_2_3"

    def test_returns_none_for_no_files(self):
        from app.api.endpoints.orchestrator import _extract_topic_id

        assert _extract_topic_id(None) is None
        assert _extract_topic_id({}) is None

    def test_returns_none_for_missing_topic_json(self):
        from app.api.endpoints.orchestrator import _extract_topic_id

        assert _extract_topic_id({"/other.json": {"content": "{}"}}) is None

    def test_handles_dict_content(self):
        from app.api.endpoints.orchestrator import _extract_topic_id

        files = {"/topic.json": {"content": {"topic_id": "q_5"}}}
        assert _extract_topic_id(files) == "q_5"

    def test_handles_invalid_json(self):
        from app.api.endpoints.orchestrator import _extract_topic_id

        files = {"/topic.json": {"content": "not valid json"}}
        assert _extract_topic_id(files) is None
