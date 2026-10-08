import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from ai_os_context.memory import (
    MemorySelectionStale, MemoryUnavailable, record_memory_selection, search_global_memory,
)


class _Response:
    def __init__(self, value):
        self._body = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


class MemoryTests(unittest.TestCase):
    def test_requires_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MemoryUnavailable):
                search_global_memory("browser-agent")

    def test_calls_rpc_and_bounds_limit(self):
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _Response(
                [
                    {
                        "chunk_id": "tool.browser-agent#001",
                        "document_id": "tool.browser-agent",
                        "score": 0.9,
                    }
                ]
            )

        with patch.dict(
            os.environ,
            {
                "AIOS_MEMORY_SUPABASE_URL": "https://example.supabase.co",
                "AIOS_MEMORY_SUPABASE_KEY": "secret",
            },
            clear=True,
        ):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = search_global_memory(
                    "browser-agent timeout",
                    limit=500,
                    tools=["browser-agent"],
                )

        self.assertEqual(
            captured["url"],
            "https://example.supabase.co/rest/v1/rpc/aios_memory_search",
        )
        self.assertEqual(captured["body"]["p_limit"], 50)
        self.assertEqual(captured["body"]["p_tools"], ["browser-agent"])
        self.assertIsNone(captured["body"]["p_query_embedding"])
        self.assertEqual(result["mode"], "lexical")
        self.assertEqual(result["count"], 1)

    def test_uses_compatible_embedding_when_available(self):
        calls = []

        def fake_urlopen(request, timeout=0):
            calls.append(request.full_url)
            if request.full_url == "https://embed.example/v1":
                return _Response({"embedding": [0.1] * 1536})
            return _Response([])

        with patch.dict(
            os.environ,
            {
                "AIOS_MEMORY_SUPABASE_URL": "https://example.supabase.co",
                "AIOS_MEMORY_SUPABASE_KEY": "secret",
                "AIOS_MEMORY_EMBEDDING_ENDPOINT": "https://embed.example/v1",
            },
            clear=True,
        ):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = search_global_memory("AIOS architecture")

        self.assertEqual(result["mode"], "hybrid")
        self.assertEqual(calls[0], "https://embed.example/v1")
        self.assertIn("/rest/v1/rpc/aios_memory_search", calls[1])
        self.assertEqual(len(calls), 2, "search must not write selection feedback")

    def test_selection_only_sends_explicit_results_and_deduplicates(self):
        chosen = {"chunk_id": "selected#002", "source_commit": "current"}
        with patch.dict(os.environ, {"AIOS_MEMORY_SUPABASE_URL": "https://example.supabase.co",
                                    "AIOS_MEMORY_SUPABASE_KEY": "sb_secret_test"}, clear=True):
            with patch("urllib.request.urlopen", return_value=_Response([
                {"chunk_id": "selected#002", "last_selected_at": "2026-10-09T00:00:00Z"}
            ])) as transport:
                result = record_memory_selection([chosen, chosen])
        request = transport.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/rpc/aios_memory_mark_selected"))
        self.assertEqual(json.loads(request.data), {"p_selections": [chosen], "p_scope": "global"})
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(result["count"], 1)
        self.assertEqual(transport.call_count, 1)

    def test_invalid_selection_never_reaches_database(self):
        for value in (None, [], {}, [None], [{"chunk_id": "x"}],
                      [{"chunk_id": "x", "source_commit": ""}],
                      [{"chunk_id": "x", "source_commit": "a"}] * 51):
            with self.subTest(value=value), patch("urllib.request.urlopen") as transport:
                with self.assertRaises(ValueError):
                    record_memory_selection(value)
                transport.assert_not_called()

    def test_stale_selection_does_not_retry_or_claim_success(self):
        with patch.dict(os.environ, {"AIOS_MEMORY_SUPABASE_URL": "https://example.supabase.co",
                                    "AIOS_MEMORY_SUPABASE_KEY": "secret"}, clear=True):
            with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
                "https://example.supabase.co", 400, "stale", {}, None
            )) as transport:
                with self.assertRaises(MemorySelectionStale):
                    record_memory_selection([{"chunk_id": "x", "source_commit": "old"}])
                self.assertEqual(transport.call_count, 1)

    def test_missing_acknowledgement_is_not_success(self):
        with patch.dict(os.environ, {"AIOS_MEMORY_SUPABASE_URL": "https://example.supabase.co",
                                    "AIOS_MEMORY_SUPABASE_KEY": "secret"}, clear=True):
            with patch("urllib.request.urlopen", return_value=_Response([])):
                with self.assertRaises(MemoryUnavailable):
                    record_memory_selection([{"chunk_id": "x", "source_commit": "a"}])


if __name__ == "__main__":
    unittest.main()
