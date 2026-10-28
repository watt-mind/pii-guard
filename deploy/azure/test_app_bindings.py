"""Focused domain-preservation boundary tests, no cloud access."""

import subprocess
import unittest

from app_bindings import existing_bindings


class BindingReadTests(unittest.TestCase):
    def test_successful_bindings_are_preserved(self) -> None:
        result = subprocess.CompletedProcess(
            [],
            0,
            '[{"name":"guard.example.com","bindingType":"SniEnabled","certificateId":"/synthetic/cert"}]',
            "",
        )
        actual = existing_bindings(
            "app", "group", "stage", run=lambda *a, result=result, **k: result
        )
        self.assertEqual(actual[0]["certificateId"], "/synthetic/cert")

    def test_successful_null_is_unbound(self) -> None:
        result = subprocess.CompletedProcess([], 0, "null", "")
        self.assertEqual(
            existing_bindings("app", "group", "stage", run=lambda *a, result=result, **k: result),
            [],
        )

    def test_proven_missing_app_allows_first_stage_only(self) -> None:
        result = subprocess.CompletedProcess(
            [], 3, "", "ERROR: (ContainerAppNotFound) synthetic app not found"
        )
        self.assertEqual(
            existing_bindings("app", "group", "stage", run=lambda *a, result=result, **k: result),
            [],
        )
        with self.assertRaisesRegex(ValueError, "unavailable"):
            existing_bindings("app", "group", "enable", run=lambda *a, result=result, **k: result)

    def test_authorization_and_network_errors_never_clear_bindings(self) -> None:
        for error in (
            "ERROR: (AuthorizationFailed) synthetic refusal",
            "network request timed out",
        ):
            with self.subTest(error=error):
                result = subprocess.CompletedProcess([], 1, "", error)
                with self.assertRaisesRegex(ValueError, "unavailable"):
                    existing_bindings(
                        "app", "group", "stage", run=lambda *a, result=result, **k: result
                    )


if __name__ == "__main__":
    unittest.main()
