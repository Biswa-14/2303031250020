# Stage 1

## Core Notification Actions

The notification platform should support creating notifications, listing notifications for the logged-in user, fetching a single notification, marking notifications as read or unread, deleting or archiving notifications, and streaming real-time updates. All user-facing endpoints should identify the user from the authentication token instead of accepting a `studentId` in the URL for normal student flows.

## Headers

All protected REST endpoints use these headers:

```http
Authorization: Bearer <access_token>
Content-Type: application/json
Accept: application/json
X-Request-Id: <uuid>
```

Server responses should include:

```http
Content-Type: application/json
X-Request-Id: <same uuid>
Cache-Control: no-store
```

## REST API Contract

### Create Notification

```http
POST /api/v1/notifications
```

Request:

```json
{
  "recipientId": "student_1042",
  "channel": "in_app",
  "type": "placement",
  "title": "Placement Drive",
  "message": "A new placement drive is open for registration.",
  "metadata": {
    "companyId": "cmp_22",
    "driveId": "drv_98"
  },
  "priority": 90,
  "dedupeKey": "placement:drv_98:student_1042"
}
```

Response:

```json
{
  "id": "ntf_01JZ1",
  "recipientId": "student_1042",
  "channel": "in_app",
  "type": "placement",
  "title": "Placement Drive",
  "message": "A new placement drive is open for registration.",
  "isRead": false,
  "createdAt": "2026-06-30T09:15:00Z",
  "metadata": {
    "companyId": "cmp_22",
    "driveId": "drv_98"
  }
}
```

### List My Notifications

```http
GET /api/v1/notifications?status=unread&type=placement&limit=20&cursor=eyJjcmVhdGVkQXQiOiIyMDI2In0
```

Response:

```json
{
  "data": [
    {
      "id": "ntf_01JZ1",
      "type": "placement",
      "title": "Placement Drive",
      "message": "A new placement drive is open for registration.",
      "isRead": false,
      "createdAt": "2026-06-30T09:15:00Z"
    }
  ],
  "page": {
    "limit": 20,
    "nextCursor": "eyJjcmVhdGVkQXQiOiIyMDI2LTA2LTMwIn0"
  },
  "unreadCount": 14
}
```

### Get One Notification

```http
GET /api/v1/notifications/{notificationId}
```

Response:

```json
{
  "id": "ntf_01JZ1",
  "type": "placement",
  "title": "Placement Drive",
  "message": "A new placement drive is open for registration.",
  "isRead": false,
  "createdAt": "2026-06-30T09:15:00Z",
  "metadata": {
    "companyId": "cmp_22",
    "driveId": "drv_98"
  }
}
```

### Mark One Notification Read

```http
PATCH /api/v1/notifications/{notificationId}/read
```

Request:

```json
{
  "isRead": true
}
```

Response:

```json
{
  "id": "ntf_01JZ1",
  "isRead": true,
  "readAt": "2026-06-30T09:20:00Z"
}
```

### Bulk Mark Read

```http
PATCH /api/v1/notifications/read
```

Request:

```json
{
  "notificationIds": ["ntf_01JZ1", "ntf_01JZ2"],
  "isRead": true
}
```

Response:

```json
{
  "updated": 2
}
```

### Delete Or Archive

```http
DELETE /api/v1/notifications/{notificationId}
```

Response:

```json
{
  "deleted": true
}
```

### Unread Count

```http
GET /api/v1/notifications/unread-count
```

Response:

```json
{
  "unreadCount": 14
}
```

## Real-Time Notifications

Use WebSocket or Server-Sent Events for logged-in users:

```http
GET /api/v1/notifications/stream
Authorization: Bearer <access_token>
Accept: text/event-stream
```

Example event:

```json
{
  "event": "notification.created",
  "data": {
    "id": "ntf_01JZ9",
    "type": "result",
    "title": "Result Published",
    "message": "Your assessment result is available.",
    "isRead": false,
    "createdAt": "2026-06-30T09:25:00Z"
  }
}
```

The stream should authenticate once, subscribe the connection to `student:{studentId}`, send heartbeat pings every 30 seconds, and reconnect from the client with exponential backoff.

# Stage 2

## Suggested Persistent Storage

I suggest PostgreSQL as the primary database. Notifications need strong consistency for read/unread state, deduplication, pagination by time, joins with student or campaign data, and reliable transactional writes. PostgreSQL also supports JSONB metadata, partial indexes, partitioning, and `SKIP LOCKED` for worker queues if the system later adds outbox processing.

## PostgreSQL Schema

```sql
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id BIGINT NOT NULL,
    channel VARCHAR(32) NOT NULL,
    type VARCHAR(32) NOT NULL,
    title VARCHAR(160) NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 0,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    read_at TIMESTAMPTZ,
    dedupe_key VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX ux_notifications_dedupe_key
ON notifications (dedupe_key)
WHERE dedupe_key IS NOT NULL;

CREATE INDEX ix_notifications_recipient_unread_created
ON notifications (recipient_id, is_read, created_at DESC);

CREATE INDEX ix_notifications_recipient_created
ON notifications (recipient_id, created_at DESC);

CREATE INDEX ix_notifications_type_created
ON notifications (type, created_at DESC);
```

## Queries For The REST APIs

List notifications:

```sql
SELECT id, type, title, message, is_read, created_at, metadata
FROM notifications
WHERE recipient_id = $1
  AND archived_at IS NULL
  AND ($2::boolean IS NULL OR is_read = $2)
  AND ($3::text IS NULL OR type = $3)
  AND ($4::timestamptz IS NULL OR created_at < $4)
ORDER BY created_at DESC
LIMIT $5;
```

Unread count:

```sql
SELECT count(*)
FROM notifications
WHERE recipient_id = $1
  AND is_read = FALSE
  AND archived_at IS NULL;
```

Mark one notification read:

```sql
UPDATE notifications
SET is_read = TRUE,
    read_at = now()
WHERE id = $1
  AND recipient_id = $2
RETURNING id, is_read, read_at;
```

Bulk mark read:

```sql
UPDATE notifications
SET is_read = TRUE,
    read_at = now()
WHERE recipient_id = $1
  AND id = ANY($2::uuid[])
RETURNING id;
```

Insert notification idempotently:

```sql
INSERT INTO notifications (
    recipient_id, channel, type, title, message, metadata, priority, dedupe_key
)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL
DO NOTHING
RETURNING *;
```

## Problems As Data Volume Increases

Large volumes can make unread-count queries expensive, slow down `ORDER BY created_at`, increase index size, create write contention during bulk sends, and make old notifications costly to retain. The API can also overload the database if every page load performs fresh reads.

## Scaling The Storage

Use cursor pagination instead of offset pagination, keep the partial unread index, partition notifications by month or by hash of `recipient_id`, archive old rows to cheaper storage, and maintain a separate `notification_counters` table for unread counts. For very high fan-out announcements, store one campaign row plus per-user delivery/read state instead of duplicating the entire message body 50,000 times.

# Stage 3

The slow query is:

```sql
SELECT *
FROM notifications
WHERE studentID = 1042
  AND isRead = false
ORDER BY createdAt DESC;
```

## Why It Is Slow

With 5,000,000 notifications, the database may scan many rows for `studentID = 1042`, filter unread rows, and then sort by `createdAt DESC`. The `SELECT *` also reads more data than the notification list usually needs.

## Fixes

Use consistent snake_case column names and create a composite index that matches the filter and sort:

```sql
CREATE INDEX ix_notifications_student_unread_created
ON notifications (student_id, is_read, created_at DESC);
```

If most notifications are already read, a partial index is smaller and faster:

```sql
CREATE INDEX ix_notifications_student_unread_only_created
ON notifications (student_id, created_at DESC)
WHERE is_read = FALSE;
```

Then query only the columns needed and use a limit:

```sql
SELECT id, type, title, message, created_at, metadata
FROM notifications
WHERE student_id = 1042
  AND is_read = FALSE
ORDER BY created_at DESC
LIMIT 20;
```

For the next page, avoid `OFFSET` and use a cursor:

```sql
SELECT id, type, title, message, created_at, metadata
FROM notifications
WHERE student_id = 1042
  AND is_read = FALSE
  AND created_at < $1
ORDER BY created_at DESC
LIMIT 20;
```

Expected result: the database can seek directly to unread notifications for one student in descending creation order and return the first page without sorting millions of rows.

# Stage 4

Fetching notifications from the database on every page load for every student creates repeated reads for data that often has not changed. I would combine real-time delivery, caching, and client-side state.

## Suggested Strategy

Use a WebSocket or SSE stream for new notifications after login. On first load, fetch the first page and unread count through REST. After that, push newly created notifications through the stream and update the client state immediately. If the stream disconnects, the client reconnects and performs a lightweight sync using `lastSeenCreatedAt`.

## Performance Improvements

Cache each user's first unread page and unread count in Redis with a short TTL, such as 30 to 120 seconds. Invalidate or update the cache when a new notification is created or when the user marks a notification as read. For counters, keep `notification_counters(student_id, unread_count)` updated transactionally so the UI does not run `COUNT(*)` on every page load.

## Tradeoffs

WebSockets give the best user experience but require connection management and horizontal scaling through a pub/sub layer. SSE is simpler and works well for server-to-client events, but it is one-way. Redis caching reduces read pressure, but cache invalidation must be handled carefully to avoid stale unread counts. Client-side state reduces repeated requests, but it must resync after tab refresh, logout, or network failure.

# Stage 5

The provided pseudocode sends email, writes the database row, and pushes real-time notifications inside one synchronous loop:

```text
for student_id in student_ids:
    send_email(student_id, message)
    save_to_db(student_id, message)
    push_to_app(student_id, message)
```

## Shortcomings

One failed email stops or complicates the rest of the batch. The request stays open for too long, retries can create duplicate notifications, and there is no durable record of pending work. Email delivery, database writes, and real-time push have different reliability requirements, so they should not be treated as one atomic operation.

If email failed for 200 students midway, the system must know exactly which students failed, retry only those deliveries, and avoid sending duplicates to students who already received the message.

## Redesign

Save the notification intent first, then process delivery asynchronously through queues and workers. Database persistence should be the source of truth. Email and in-app push are side effects that can be retried independently.

Revised pseudocode:

```text
function notify_all(student_ids, message):
    campaign_id = create_campaign(message, status="queued")

    for chunk in chunks(student_ids, 1000):
        begin_transaction()
        for student_id in chunk:
            notification_id = insert_notification(
                campaign_id=campaign_id,
                student_id=student_id,
                message=message,
                dedupe_key=f"{campaign_id}:{student_id}"
            )
            enqueue_outbox(
                notification_id=notification_id,
                channel="email",
                idempotency_key=f"email:{campaign_id}:{student_id}"
            )
            enqueue_outbox(
                notification_id=notification_id,
                channel="in_app",
                idempotency_key=f"in_app:{campaign_id}:{student_id}"
            )
        commit_transaction()

    return { "campaignId": campaign_id, "status": "queued" }

function delivery_worker():
    while true:
        job = claim_next_outbox_job(status="pending", lock="skip_locked")
        if job is None:
            sleep()
            continue

        try:
            if job.channel == "email":
                email_provider.send(job.idempotency_key, job.payload)
            if job.channel == "in_app":
                realtime_gateway.push(job.student_id, job.payload)

            mark_job_sent(job.id)
        except TemporaryError:
            retry_later(job.id, exponential_backoff=True)
        except PermanentError:
            mark_job_failed(job.id)
```

Saving to the DB and sending email should not happen together in the same synchronous request. The database transaction should create notifications and outbox jobs. Workers should handle delivery with retries, dead-letter queues, rate limits, provider idempotency keys, and monitoring.

# Stage 6

Priority is determined by notification type weight and recency:

```text
placement > result > event
```

The implementation is in `priority_notifications.py`. It fetches the provided Notification API, filters unread notifications, and maintains only the top 10 items in memory using a min-heap. This is efficient for new notifications because each incoming unread notification costs `O(log 10)`, which is effectively constant time.

## Maintaining Top 10 Efficiently

For an initial API response of `n` notifications, the algorithm is `O(n log 10)` and uses `O(10)` heap space besides the fetched response. For new notifications arriving later through WebSocket or SSE, pass each new notification through the same ranking function:

```text
if heap has fewer than 10 items:
    push notification
else if new notification ranks higher than the smallest item in heap:
    replace smallest item
```

The ranking tuple is:

```text
(type_weight, created_at_timestamp, notification_id)
```

This makes placement notifications outrank result notifications, result notifications outrank event notifications, and newer notifications win within the same type.

## Running The Code

```powershell
$env:NOTIFICATION_API_TOKEN="your_token_here"
python .\notification_system_submission\priority_notifications.py
```

During local verification, the API responded with:

```json
{
  "message": "An authorization header is required"
}
```

So the script requires `NOTIFICATION_API_TOKEN` and sends it as:

```http
Authorization: Bearer <token>
```
