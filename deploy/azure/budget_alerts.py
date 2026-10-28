"""Select monitored actual-spend alerts by semantics, independent of Azure map-key casing."""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal, InvalidOperation

_ACTION_GROUP = re.compile(
    r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Insights/actionGroups/[^/]+",
    re.IGNORECASE,
)
_ERROR = "Enabled Actual 50% budget notification with valid action groups is required"


def actual_50_groups(notifications: object) -> list[str]:
    if not isinstance(notifications, dict) or not notifications:
        raise ValueError(_ERROR)
    groups: dict[str, str] = {}
    for notification in notifications.values():
        if not isinstance(notification, dict):
            raise ValueError(_ERROR)
        if notification.get("enabled") is not True:
            continue
        kind = notification.get("thresholdType")
        operator = notification.get("operator")
        if not isinstance(kind, str) or kind.casefold() != "actual":
            continue
        if not isinstance(operator, str) or operator.casefold() not in {
            "greaterthan",
            "greaterthanorequalto",
        }:
            continue
        threshold = notification.get("threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            continue
        try:
            amount = Decimal(str(threshold))
        except InvalidOperation:
            continue
        if not amount.is_finite() or amount != 50:
            continue
        recipients = notification.get("contactGroups")
        if (
            not isinstance(recipients, list)
            or not recipients
            or not all(
                isinstance(group, str) and _ACTION_GROUP.fullmatch(group) for group in recipients
            )
        ):
            raise ValueError(_ERROR)
        for group in recipients:
            groups.setdefault(group.casefold(), group)
    if not groups:
        raise ValueError(_ERROR)
    return list(groups.values())


def main() -> int:
    try:
        groups = actual_50_groups(json.load(sys.stdin))
    except (ValueError, TypeError, OSError):
        print(_ERROR, file=sys.stderr)
        return 1
    print(json.dumps(groups))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
