import json
import os
import unittest
from unittest.mock import patch

from ai_os_context.memory import MemoryUnavailable, search_global_memory


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


if __name__ == "__main__":
    unittest.main()
