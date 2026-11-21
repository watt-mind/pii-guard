from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from muse_drift import PIN_FILE, pinned_version, report, served_version


def channel(**overrides: object) -> dict:
    base = {
        "channel": "muse-stable",
        "version": "1.4.24-R9131.1",
        "manifest_url": "https://lookaside.facebook.com/lookaside/muse/download/?channel=muse",
        "urgency": "none",
    }
    return {**base, **overrides}


class PinnedVersionTests(unittest.TestCase):
    def test_reads_the_pin_from_muse_code_py(self) -> None:
        pin = pinned_version(PIN_FILE.read_text(encoding="utf-8"))
        self.assertRegex(pin, r"^\d+\.\d+\.\d+-R\d+\.\d+$")

    def test_a_missing_pin_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            pinned_version('OTHER = "1.0"\n')


class ServedVersionTests(unittest.TestCase):
    def test_reads_the_version(self) -> None:
        self.assertEqual(served_version(channel()), "1.4.24-R9131.1")

    def test_rejects_another_channel_or_a_bad_version(self) -> None:
        for bad in (
            channel(channel="muse-beta"),
            channel(version="1.4.24; rm -rf /"),
            channel(version=None),
            ["not", "an", "object"],
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                served_version(bad)


class ReportTests(unittest.TestCase):
    def test_same_version_is_no_drift(self) -> None:
        drift, message = report("1.4.15-R8339.1", "1.4.15-R8339.1")
        self.assertFalse(drift)
        self.assertIn("pinned 1.4.15-R8339.1", message)

    def test_a_newer_release_is_drift_with_what_to_do(self) -> None:
        drift, message = report("1.4.15-R8339.1", "1.4.24-R9131.1")
        self.assertTrue(drift)
        self.assertIn("Muse Code 1.4.24-R9131.1 is out", message)
        self.assertIn("MUSE_VERSION_CHECKED", message)


if __name__ == "__main__":
    unittest.main()
