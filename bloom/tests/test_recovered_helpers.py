"""Regression tests for isolated helpers in the recovered BLOOM source snapshot.

These tests do not start the desktop app or make network/API calls.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jarvis import brand, language, permissions


class RecoveredHelperTests(unittest.TestCase):
    def test_turkish_suffix_is_preserved_in_lowercase_form(self) -> None:
        self.assertEqual(brand.suffixed("KAAN", "acc", upper_case=False), "KAAN'ı")
        self.assertEqual(brand.suffixed("ECE", "acc", upper_case=False), "ECE'yi")

    def test_automatic_transcription_uses_valid_language_codes_key(self) -> None:
        with patch.object(language.settings, "get", return_value="auto"):
            self.assertEqual(
                language.transcription(),
                {"language_codes": ["tr-TR", "en-US"]},
            )

    def test_blocked_windows_microphone_opens_privacy_settings(self) -> None:
        open_settings = Mock(return_value=True)
        win_permissions = SimpleNamespace(open_settings=open_settings)
        with (
            patch.object(permissions.paths, "IS_WIN", True),
            patch.object(permissions, "_win", win_permissions, create=True),
        ):
            self.assertTrue(permissions.open_mic_help("blocked"))
        open_settings.assert_called_once_with("microphone", force=True)


if __name__ == "__main__":
    unittest.main()
