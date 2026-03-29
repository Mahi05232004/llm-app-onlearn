"""Tests for parse_agent_response() — extracting suggestions, actions, next_question."""

import pytest

from app.api.helpers.sse_streaming import parse_agent_response


class TestParseSuggestions:
    """Should extract pipe-separated suggestions from <suggestions> tags."""

    def test_basic_suggestions(self):
        response = "Here's my answer <suggestions>Try approach A|Think about B</suggestions>"
        result = parse_agent_response(response)
        assert result["suggestions"] == ["Try approach A", "Think about B"]

    def test_single_suggestion(self):
        response = "Answer <suggestions>Show an example</suggestions>"
        result = parse_agent_response(response)
        assert result["suggestions"] == ["Show an example"]

    def test_three_suggestions(self):
        response = "<suggestions>Option A|Option B|Option C</suggestions>"
        result = parse_agent_response(response)
        assert len(result["suggestions"]) == 3

    def test_whitespace_trimmed(self):
        response = "<suggestions>  A  |  B  </suggestions>"
        result = parse_agent_response(response)
        assert result["suggestions"] == ["A", "B"]

    def test_empty_suggestions_filtered(self):
        response = "<suggestions>A||B|</suggestions>"
        result = parse_agent_response(response)
        assert result["suggestions"] == ["A", "B"]


class TestParseActions:
    """Should extract pipe-separated actions from <actions> tags."""

    def test_basic_actions(self):
        response = "text <actions>go_to_code|im_done|next_question</actions>"
        result = parse_agent_response(response)
        assert result["actions"] == ["go_to_code", "im_done", "next_question"]

    def test_single_action(self):
        response = "<actions>im_done</actions>"
        result = parse_agent_response(response)
        assert result["actions"] == ["im_done"]


class TestParseNextQuestion:
    """Should extract question ID from <next_question> tags."""

    def test_basic_next_question(self):
        response = "text <next_question>q_1_2_3</next_question>"
        result = parse_agent_response(response)
        assert result["next_question_id"] == "q_1_2_3"

    def test_no_next_question(self):
        response = "Just a plain response"
        result = parse_agent_response(response)
        assert result["next_question_id"] is None


class TestParseNoTags:
    """Should gracefully handle responses without any tags."""

    def test_plain_response(self):
        result = parse_agent_response("Just a normal response without any tags")
        assert result["suggestions"] == []
        assert result["actions"] == []
        assert result["next_question_id"] is None

    def test_empty_response(self):
        result = parse_agent_response("")
        assert result["suggestions"] == []
        assert result["actions"] == []
        assert result["next_question_id"] is None


class TestParseAllTags:
    """Should extract all tags from a response containing all of them."""

    def test_full_response(self):
        response = (
            "Great job! Let's move on.\n"
            "<suggestions>Review arrays|Try linked lists</suggestions>\n"
            "<actions>next_question</actions>\n"
            "<next_question>valid-anagram</next_question>"
        )
        result = parse_agent_response(response)
        assert result["suggestions"] == ["Review arrays", "Try linked lists"]
        assert result["actions"] == ["next_question"]
        assert result["next_question_id"] == "valid-anagram"
