"""Unit tests for state helpers: merge_files, _read_file_json, _read_file_json_from_files."""
import json
import pytest

from app.supervisor.graph.state import merge_files
from app.supervisor.agents.nodes import _read_file_json, _read_file_json_from_files
from tests.supervisor.conftest import make_state, make_files, make_routing


class TestMergeFiles:
    """Tests for the merge_files state reducer."""
    
    def test_merge_empty_existing(self):
        result = merge_files({}, {"/a.json": {"content": "{}"}})
        assert "/a.json" in result
    
    def test_merge_empty_new(self):
        existing = {"/a.json": {"content": "{}"}}
        result = merge_files(existing, {})
        assert "/a.json" in result
    
    def test_merge_both_empty(self):
        assert merge_files({}, {}) == {}
    
    def test_merge_preserves_existing(self):
        """Existing files should not be lost when new files are added."""
        existing = {"/routing.json": {"content": '{"active_agent": "master"}'}}
        new = {"/plan.json": {"content": '{"weeks": []}'}}
        result = merge_files(existing, new)
        assert "/routing.json" in result
        assert "/plan.json" in result
    
    def test_merge_new_overwrites_on_conflict(self):
        """New files take precedence on key conflict."""
        existing = {"/a.json": {"content": "old"}}
        new = {"/a.json": {"content": "new"}}
        result = merge_files(existing, new)
        assert result["/a.json"]["content"] == "new"
    
    def test_none_handling(self):
        assert merge_files(None, {"/a.json": {}}) == {"/a.json": {}}
        assert merge_files({"/a.json": {}}, None) == {"/a.json": {}}


class TestReadFileJson:
    """Tests for _read_file_json (reads from state)."""
    
    def test_reads_string_content(self):
        state = make_state(files={
            "/test.json": {"content": '{"key": "value"}'}
        })
        result = _read_file_json(state, "/test.json")
        assert result == {"key": "value"}
    
    def test_reads_list_of_lines_content(self):
        """StateBackend stores content as list of lines."""
        state = make_state(files={
            "/test.json": {"content": ['{"key":', '"value"}']}
        })
        result = _read_file_json(state, "/test.json")
        assert result == {"key": "value"}
    
    def test_missing_file_returns_empty_dict(self):
        state = make_state(files={})
        result = _read_file_json(state, "/nonexistent.json")
        assert result == {}
    
    def test_invalid_json_returns_empty_dict(self):
        state = make_state(files={
            "/test.json": {"content": "not valid json"}
        })
        result = _read_file_json(state, "/test.json")
        assert result == {}
    
    def test_file_without_content_key(self):
        state = make_state(files={
            "/test.json": {"metadata": {"type": "json"}}
        })
        result = _read_file_json(state, "/test.json")
        assert result == {}


class TestReadFileJsonFromFiles:
    """Tests for _read_file_json_from_files (reads from raw files dict)."""
    
    def test_reads_from_raw_dict(self):
        files = {"/test.json": {"content": '{"a": 1}'}}
        result = _read_file_json_from_files(files, "/test.json")
        assert result == {"a": 1}
    
    def test_list_of_lines(self):
        files = {"/test.json": {"content": ['{"a":', '1}']}}
        result = _read_file_json_from_files(files, "/test.json")
        assert result == {"a": 1}
    
    def test_missing_file(self):
        result = _read_file_json_from_files({}, "/nope.json")
        assert result == {}
    
    def test_invalid_json(self):
        files = {"/test.json": {"content": "broken"}}
        result = _read_file_json_from_files(files, "/test.json")
        assert result == {}
