import unittest

from ai_os_context.dream import build_dream_bundle


class NightlyContextTests(unittest.TestCase):
    def test_builder_is_available(self):
        self.assertTrue(callable(build_dream_bundle))
