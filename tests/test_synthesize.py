"""Test synthesize.py helper functions — cosine similarity, tag overlap, dedup, slugify.

No network calls, no LLM calls, no database access. Pure unit tests.
Mocks lib.embed to avoid sentence-transformers import requirement.
"""

import json
import struct
import sqlite3
import sys
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixture: mock lib.embed before cron.synthesize imports it
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_embed_import():
    """Mock lib.embed so cron.synthesize can import without sentence-transformers."""
    if "lib.embed" not in sys.modules:
        mock_embed = MagicMock()
        mock_embed.embed_json = MagicMock(return_value="[0.0]")
        mock_embed.embed = MagicMock(return_value=[0.0] * 384)
        mock_embed.DIMS = 384
        sys.modules["lib.embed"] = mock_embed


# ---------------------------------------------------------------------------
# _parse_tags
# ---------------------------------------------------------------------------

class TestParseTags:
    def test_valid_json_tags(self):
        from src.cron.synthesize import _parse_tags
        result = _parse_tags(json.dumps(["AI", "  Machine Learning  ", "  "]))
        assert result == ["ai", "machine learning"]

    def test_empty_string(self):
        from src.cron.synthesize import _parse_tags
        assert _parse_tags("") == []

    def test_none_input(self):
        from src.cron.synthesize import _parse_tags
        assert _parse_tags(None) == []

    def test_invalid_json(self):
        from src.cron.synthesize import _parse_tags
        assert _parse_tags("{invalid") == []

    def test_non_list_json(self):
        from src.cron.synthesize import _parse_tags
        assert _parse_tags('{"key": "value"}') == []

    def test_tags_capped_at_max(self):
        from src.cron.synthesize import _parse_tags
        tags = [f"tag{i}" for i in range(20)]
        result = _parse_tags(json.dumps(tags))
        assert len(result) == 15  # MAX_TAGS_PER_ENTRY

    def test_strips_and_lowercases(self):
        from src.cron.synthesize import _parse_tags
        result = _parse_tags(json.dumps(["  Deep Learning  ", "NLP"]))
        assert result == ["deep learning", "nlp"]


# ---------------------------------------------------------------------------
# _unpack_embedding
# ---------------------------------------------------------------------------

class TestUnpackEmbedding:
    def test_unpack_384_floats(self):
        from src.cron.synthesize import _unpack_embedding
        floats = [0.1] * 384
        blob = struct.pack(f"{384}f", *floats)
        result = _unpack_embedding(blob)
        assert len(result) == 384
        assert all(abs(v - 0.1) < 1e-6 for v in result)

    def test_unpack_varied_floats(self):
        from src.cron.synthesize import _unpack_embedding
        floats = [float(i) / 384 for i in range(384)]
        blob = struct.pack(f"{384}f", *floats)
        result = _unpack_embedding(blob)
        assert len(result) == 384
        assert abs(result[0] - 0.0) < 1e-6
        assert abs(result[383] - 383.0 / 384) < 1e-6


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self):
        from src.cron.synthesize import _cosine_similarity
        v = [1.0, 2.0, 3.0]
        result = _cosine_similarity(v, v)
        assert abs(result - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        from src.cron.synthesize import _cosine_similarity
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        result = _cosine_similarity(a, b)
        assert abs(result - 0.0) < 1e-6

    def test_opposite_vectors(self):
        from src.cron.synthesize import _cosine_similarity
        a = [1.0, 2.0, 3.0]
        b = [-1.0, -2.0, -3.0]
        result = _cosine_similarity(a, b)
        assert abs(result - (-1.0)) < 1e-6

    def test_zero_vector(self):
        from src.cron.synthesize import _cosine_similarity
        result = _cosine_similarity([0.0, 0.0], [1.0, 2.0])
        assert result == 0.0

    def test_both_zero_vectors(self):
        from src.cron.synthesize import _cosine_similarity
        result = _cosine_similarity([0.0, 0.0], [0.0, 0.0])
        assert result == 0.0

    def test_similar_non_identical(self):
        from src.cron.synthesize import _cosine_similarity
        a = [1.0, 1.0, 1.0]
        b = [1.0, 1.0, 0.9]
        result = _cosine_similarity(a, b)
        assert 0.9 < result < 1.0


# ---------------------------------------------------------------------------
# _tag_overlap
# ---------------------------------------------------------------------------

class TestTagOverlap:
    def test_full_overlap(self):
        from src.cron.synthesize import _tag_overlap
        result = _tag_overlap(["ai", "ml", "dl"], ["ai", "ml", "dl"])
        assert result == 1.0

    def test_partial_overlap(self):
        from src.cron.synthesize import _tag_overlap
        result = _tag_overlap(["ai", "ml", "dl"], ["ai", "ml"])
        assert result == 1.0  # 2 / min(3, 2) = 1.0

    def test_no_overlap(self):
        from src.cron.synthesize import _tag_overlap
        result = _tag_overlap(["ai", "ml"], ["python", "rust"])
        assert result == 0.0

    def test_empty_first(self):
        from src.cron.synthesize import _tag_overlap
        result = _tag_overlap([], ["ai", "ml"])
        assert result == 0.0

    def test_empty_second(self):
        from src.cron.synthesize import _tag_overlap
        result = _tag_overlap(["ai", "ml"], [])
        assert result == 0.0

    def test_both_empty(self):
        from src.cron.synthesize import _tag_overlap
        result = _tag_overlap([], [])
        assert result == 0.0

    def test_one_common(self):
        from src.cron.synthesize import _tag_overlap
        result = _tag_overlap(["ai", "ml", "dl", "nlp"], ["ai", "python", "rust", "go"])
        assert result == 1.0 / 4


# ---------------------------------------------------------------------------
# _get_existing_synthesis_pairs
# ---------------------------------------------------------------------------

class TestExistingSynthesisPairs:
    def test_empty_db(self, tmp_db):
        from src.cron.synthesize import _get_existing_synthesis_pairs
        pairs = _get_existing_synthesis_pairs(tmp_db)
        assert pairs == set()

    def test_with_synthesized_entries(self, tmp_db):
        from src.cron.synthesize import _get_existing_synthesis_pairs
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type, source_refs, created_at)
               VALUES (?, ?, ?, ?, 'synthesis', ?, datetime('now'))""",
            ("syn-1", "pliny://synthesis/syn-1", "Syn1", "content",
             json.dumps(["entry-a", "entry-b"])),
        )
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type, source_refs, created_at)
               VALUES (?, ?, ?, ?, 'synthesis', ?, datetime('now'))""",
            ("syn-2", "pliny://synthesis/syn-2", "Syn2", "content",
             json.dumps(["entry-c", "entry-d"])),
        )
        tmp_db.commit()
        pairs = _get_existing_synthesis_pairs(tmp_db)
        assert ("entry-a", "entry-b") in pairs
        assert ("entry-c", "entry-d") in pairs

    def test_sorts_pair_ids(self, tmp_db):
        from src.cron.synthesize import _get_existing_synthesis_pairs
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type, source_refs, created_at)
               VALUES (?, ?, ?, ?, 'synthesis', ?, datetime('now'))""",
            ("syn-z", "pliny://synthesis/syn-z", "Z", "content",
             json.dumps(["entry-z", "entry-a"])),
        )
        tmp_db.commit()
        pairs = _get_existing_synthesis_pairs(tmp_db)
        assert ("entry-a", "entry-z") in pairs
        assert ("entry-z", "entry-a") not in pairs

    def test_ignores_non_list_refs(self, tmp_db):
        from src.cron.synthesize import _get_existing_synthesis_pairs
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type, source_refs, created_at)
               VALUES (?, ?, ?, ?, 'synthesis', ?, datetime('now'))""",
            ("syn-3", "pliny://synthesis/syn-3", "Syn3", "content",
             json.dumps(["single-src"])),
        )
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type, source_refs, created_at)
               VALUES (?, ?, ?, ?, 'synthesis', ?, datetime('now'))""",
            ("syn-4", "pliny://synthesis/syn-4", "Syn4", "content",
             json.dumps({"not": "a list"})),
        )
        tmp_db.commit()
        pairs = _get_existing_synthesis_pairs(tmp_db)
        assert len(pairs) == 0

    def test_ignores_empty_refs(self, tmp_db):
        from src.cron.synthesize import _get_existing_synthesis_pairs
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type, source_refs, created_at)
               VALUES (?, ?, ?, ?, 'synthesis', ?, datetime('now'))""",
            ("syn-5", "pliny://synthesis/syn-5", "Syn5", "content", "[]"),
        )
        tmp_db.commit()
        pairs = _get_existing_synthesis_pairs(tmp_db)
        assert len(pairs) == 0


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_basic_title(self):
        from src.cron.synthesize import _slugify
        result = _slugify("Deep Learning vs Machine Learning")
        assert result == "deep-learning-vs-machine-learning"

    def test_special_characters(self):
        from src.cron.synthesize import _slugify
        result = _slugify("AI & ML: The Future!")
        assert result == "ai-ml-the-future"

    def test_truncates_at_80(self):
        from src.cron.synthesize import _slugify
        long_title = "a " * 100
        result = _slugify(long_title)
        assert len(result) <= 80

    def test_empty_uses_fallback(self):
        from src.cron.synthesize import _slugify
        result = _slugify("!!!", fallback_a="entry-a", fallback_b="entry-b")
        assert "synthesis" in result
        assert "entry-a" in result
        assert "entry-b" in result


# ---------------------------------------------------------------------------
# _judge_pair + _write_synthesis (LLM-related, test parsing logic)
# ---------------------------------------------------------------------------

class TestJudgePairParsing:
    def test_parse_worth_it_yes(self):
        from src.cron.synthesize import _judge_pair

        entry_a = {"title": "A", "tags": ["ai"], "content": "content a"}
        entry_b = {"title": "B", "tags": ["ml"], "content": "content b"}
        mock_response = "WORTH_IT: yes\nREASON: These complement each other well."
        with patch("src.cron.synthesize.call_llm", return_value=mock_response):
            worth_it, reason = _judge_pair(entry_a, entry_b)
            assert worth_it is True
            assert reason == "These complement each other well."

    def test_parse_worth_it_no(self):
        from src.cron.synthesize import _judge_pair

        entry_a = {"title": "A", "tags": ["ai"], "content": "content a"}
        entry_b = {"title": "B", "tags": ["ai"], "content": "content b"}
        mock_response = "WORTH_IT: no\nREASON: Too similar."
        with patch("src.cron.synthesize.call_llm", return_value=mock_response):
            worth_it, reason = _judge_pair(entry_a, entry_b)
            assert worth_it is False
            assert reason == "Too similar."

    def test_parse_worth_it_case_insensitive(self):
        from src.cron.synthesize import _judge_pair

        entry_a = {"title": "A", "tags": ["ai"], "content": "content a"}
        entry_b = {"title": "B", "tags": ["ml"], "content": "content b"}
        mock_response = "worth_it: yes\nreason: Good match."
        with patch("src.cron.synthesize.call_llm", return_value=mock_response):
            worth_it, reason = _judge_pair(entry_a, entry_b)
            assert worth_it is True

    def test_parse_no_match_returns_false(self):
        from src.cron.synthesize import _judge_pair

        entry_a = {"title": "A", "tags": ["ai"], "content": "content a"}
        entry_b = {"title": "B", "tags": ["ml"], "content": "content b"}
        mock_response = "Some other response format entirely."
        with patch("src.cron.synthesize.call_llm", return_value=mock_response):
            worth_it, reason = _judge_pair(entry_a, entry_b)
            assert worth_it is False

    def test_llm_error_returns_false(self):
        from src.cron.synthesize import _judge_pair

        entry_a = {"title": "A", "tags": ["ai"], "content": "content a"}
        entry_b = {"title": "B", "tags": ["ml"], "content": "content b"}
        with patch("src.cron.synthesize.call_llm", side_effect=RuntimeError("API down")):
            worth_it, reason = _judge_pair(entry_a, entry_b)
            assert worth_it is False
            assert reason == ""


class TestWriteSynthesis:
    def test_happy_path(self):
        from src.cron.synthesize import _write_synthesis

        entry_a = {"title": "A", "tags": ["ai"], "content": "content a"}
        entry_b = {"title": "B", "tags": ["ml"], "content": "content b"}
        mock_response = "Combining A and B reveals..."
        with patch("src.cron.synthesize.call_llm", return_value=mock_response):
            result = _write_synthesis(entry_a, entry_b, "Good match")
            assert result == mock_response

    def test_llm_error_returns_failure_message(self):
        from src.cron.synthesize import _write_synthesis

        entry_a = {"title": "A", "tags": ["ai"], "content": "content a"}
        entry_b = {"title": "B", "tags": ["ml"], "content": "content b"}
        with patch("src.cron.synthesize.call_llm", side_effect=RuntimeError("timeout")):
            result = _write_synthesis(entry_a, entry_b, "Good match")
            assert result.startswith("[Synthesis failed")


class TestGenerateTitle:
    def test_happy_path(self):
        from src.cron.synthesize import _generate_title

        entry_a = {"title": "AI Revolution"}
        entry_b = {"title": "ML Basics"}
        mock_title = "AI and ML: A New Era"
        with patch("src.cron.synthesize.call_llm", return_value=mock_title):
            result = _generate_title(entry_a, entry_b, "Combined synthesis content")
            assert result == mock_title

    def test_strips_quotes(self):
        from src.cron.synthesize import _generate_title

        entry_a = {"title": "A"}
        entry_b = {"title": "B"}
        with patch("src.cron.synthesize.call_llm", return_value='"Wrapped in quotes"'):
            result = _generate_title(entry_a, entry_b, "content")
            assert result == "Wrapped in quotes"

    def test_fallback_on_short_response(self):
        from src.cron.synthesize import _generate_title

        entry_a = {"title": "AI Revolution", "id": "ai-rev"}
        entry_b = {"title": "ML Basics", "id": "ml-basics"}
        with patch("src.cron.synthesize.call_llm", return_value="ab"):
            result = _generate_title(entry_a, entry_b, "content")
            assert "×" in result

    def test_fallback_on_error(self):
        from src.cron.synthesize import _generate_title

        entry_a = {"title": "AI Revolution"}
        entry_b = {"title": "ML Basics"}
        with patch("src.cron.synthesize.call_llm", side_effect=RuntimeError("fail")):
            result = _generate_title(entry_a, entry_b, "content")
            assert "×" in result
