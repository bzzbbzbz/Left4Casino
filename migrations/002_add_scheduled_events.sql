-- migrations/002_add_scheduled_events.sql
-- Migration: Persisted scheduler events for happy moment/heist
-- Author: cursor-agent
-- Date: 2026-02-16
-- Reason: TASK-014 schedule visibility and idempotency

-- ============================================================
-- UPGRADE
-- ============================================================

CREATE TABLE IF NOT EXISTS scheduled_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    chat_id INTEGER,
    scheduled_at TEXT NOT NULL,
    timezone TEXT NOT NULL,
    source_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    metadata TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scheduled_events_source_date
ON scheduled_events (source_date);

CREATE INDEX IF NOT EXISTS idx_scheduled_events_status_time
ON scheduled_events (status, scheduled_at);

CREATE INDEX IF NOT EXISTS idx_scheduled_events_event_type
ON scheduled_events (event_type);

-- ============================================================
-- DOWNGRADE
-- ============================================================
-- To rollback (run manually if needed):
-- DROP INDEX IF EXISTS idx_scheduled_events_event_type;
-- DROP INDEX IF EXISTS idx_scheduled_events_status_time;
-- DROP INDEX IF EXISTS idx_scheduled_events_source_date;
-- DROP TABLE IF EXISTS scheduled_events;
