"""Synthetic Azure response regressions for the monitored budget admission boundary."""

import io
import json
import unittest
from unittest.mock import patch

from deploy.azure.budget_alerts import actual_50_groups, main

GROUP = (
    "/subscriptions/synthetic/resourceGroups/operations/"
    "providers/Microsoft.Insights/actionGroups/alerts"
)
OTHER = GROUP + "-other"


def notification(**overrides):
    return {
        "enabled": True,
        "operator": "GreaterThanOrEqualTo",
        "threshold": 50.0,
        "thresholdType": "Actual",
        "contactGroups": [GROUP],
        **overrides,
    }


class BudgetAlertTests(unittest.TestCase):
    def test_service_response_names_are_not_semantic(self):
        for name in ("Actual50", "actual50", "custom-name"):
            with self.subTest(name=name):
                self.assertEqual(actual_50_groups({name: notification()}), [GROUP])

    def test_matching_actual_alert_recipients_are_preserved_and_deduplicated(self):
        self.assertEqual(
            actual_50_groups(
                {
                    "first": notification(contactGroups=[GROUP, OTHER]),
                    "second": notification(thresholdType="actual", contactGroups=[GROUP.upper()]),
                }
            ),
            [GROUP, OTHER],
        )

    def test_unmonitored_or_invalid_semantics_fail_closed(self):
        for overrides in (
            {"enabled": False},
            {"enabled": "true"},
            {"threshold": 80},
            {"threshold": "50"},
            {"threshold": True},
            {"threshold": float("nan")},
            {"thresholdType": "Forecasted"},
            {"operator": "LessThan"},
            {"contactGroups": []},
            {"contactGroups": None},
            {"contactGroups": ["invalid"]},
            {"contactGroups": [GROUP, 123]},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                actual_50_groups({"actual50": notification(**overrides)})

    def test_ineligible_alert_cannot_hide_malformed_matching_alert(self):
        with self.assertRaises(ValueError):
            actual_50_groups({"valid": notification(), "invalid": notification(contactGroups=[])})

    def test_empty_or_unreadable_response_fails_without_skip_output(self):
        for value in (None, [], {}, {"actual50": None}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                actual_50_groups(value)
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch("sys.stdin", io.StringIO("not-json")),
            patch("sys.stdout", output),
            patch("sys.stderr", errors),
        ):
            self.assertEqual(main(), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn("not-json", errors.getvalue())

    def test_cli_outputs_only_validated_group_list(self):
        output = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO(json.dumps({"actual50": notification()}))),
            patch("sys.stdout", output),
        ):
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(output.getvalue()), [GROUP])


if __name__ == "__main__":
    unittest.main()
