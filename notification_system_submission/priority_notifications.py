from __future__ import annotations

import argparse
import heapq
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "http://4.224.186.213/evaluation-service/notifications"
DEFAULT_LIMIT = 10
TYPE_WEIGHTS = {
    "placement": 3,
    "result": 2,
    "event": 1,
}


@dataclass(frozen=True)
class RankedNotification:
    rank_key: tuple[int, float, str]
    notification: dict[str, Any]

    def __lt__(self, other: "RankedNotification") -> bool:
        return self.rank_key < other.rank_key


def parse_datetime(value: Any) -> datetime:
    if value is None:
        return datetime.fromtimestamp(0, tz=timezone.utc)

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)

    text = str(value).strip()
    if not text:
        return datetime.fromtimestamp(0, tz=timezone.utc)

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def extract_notifications(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("notifications", "data", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = extract_notifications(value)
            if nested:
                return nested

    return []


def is_unread(notification: dict[str, Any]) -> bool:
    for key in ("isRead", "is_read", "read"):
        if key in notification:
            return not bool(notification[key])

    status = str(notification.get("status", "")).strip().lower()
    if status:
        return status in {"unread", "new", "pending"}

    return True


def notification_type(notification: dict[str, Any]) -> str:
    for key in ("type", "category", "notificationType", "notification_type"):
        value = notification.get(key)
        if value:
            return str(value).strip().lower()
    return "event"


def created_at(notification: dict[str, Any]) -> datetime:
    for key in ("createdAt", "created_at", "timestamp", "date", "sentAt", "sent_at"):
        if key in notification:
            return parse_datetime(notification[key])
    return datetime.fromtimestamp(0, tz=timezone.utc)


def notification_id(notification: dict[str, Any]) -> str:
    for key in ("id", "_id", "notificationId", "notification_id"):
        if key in notification:
            return str(notification[key])
    return json.dumps(notification, sort_keys=True)


def rank_key(notification: dict[str, Any]) -> tuple[int, float, str]:
    type_name = notification_type(notification)
    weight = TYPE_WEIGHTS.get(type_name, 0)
    recency = created_at(notification).timestamp()
    return (weight, recency, notification_id(notification))


def top_priority_notifications(
    notifications: list[dict[str, Any]],
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    heap: list[RankedNotification] = []

    for notification in notifications:
        if not is_unread(notification):
            continue

        ranked = RankedNotification(rank_key(notification), notification)
        if len(heap) < limit:
            heapq.heappush(heap, ranked)
        elif ranked.rank_key > heap[0].rank_key:
            heapq.heapreplace(heap, ranked)

    return [
        ranked.notification
        for ranked in sorted(heap, key=lambda item: item.rank_key, reverse=True)
    ]


def fetch_notifications(api_url: str, token: str) -> list[dict[str, Any]]:
    request = Request(
        api_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )

    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    return extract_notifications(payload)


def display(notifications: list[dict[str, Any]]) -> None:
    if not notifications:
        print("No unread notifications found.")
        return

    print("Top priority unread notifications")
    print("-" * 80)
    for index, notification in enumerate(notifications, start=1):
        type_name = notification_type(notification)
        created = created_at(notification).isoformat()
        title = notification.get("title") or notification.get("message") or "(no title)"
        identifier = notification_id(notification)
        print(f"{index:>2}. [{type_name}] {title}")
        print(f"    id={identifier} createdAt={created}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch and print the top priority unread notifications."
    )
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    token = os.getenv("NOTIFICATION_API_TOKEN")
    if not token:
        print(
            "NOTIFICATION_API_TOKEN is required because the provided API rejects "
            "requests without an Authorization header.",
            file=sys.stderr,
        )
        return 2

    try:
        notifications = fetch_notifications(args.api_url, token)
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"API request failed: HTTP {error.code} {body}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"API request failed: {error}", file=sys.stderr)
        return 1

    display(top_priority_notifications(notifications, args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
