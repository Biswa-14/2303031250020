# Notification System Submission

This directory contains the Stage 1 to Stage 6 notification system submission.

## Files

- `Notification_System_Design.md` - design answers for all six stages.
- `priority_notifications.py` - Stage 6 implementation that fetches notifications from the provided API and prints the top unread priority notifications.
- `sample_output.txt` - captured local run output showing that the API is reachable but requires an authorization header.

## Run Stage 6

```bash
$env:NOTIFICATION_API_TOKEN="your_token_here"
python .\notification_system_submission\priority_notifications.py
```

The code does not hard-code or create notifications. It fetches the API response, filters unread notifications, and maintains the top 10 with a bounded heap.
