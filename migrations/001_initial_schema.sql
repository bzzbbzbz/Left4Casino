-- migrations/001_initial_schema.sql
-- Migration: Initial database schema (baseline from bot/db.py)
-- Author: cursor-agent
-- Date: 2026-02-15
-- Reason: TASK-007 baseline migration

-- ============================================================
-- UPGRADE
-- ============================================================

-- Users table (matches create_tables + ALTER columns + safe_balance for User model)
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    nickname TEXT,
    balance INTEGER NOT NULL DEFAULT 50,
    bid INTEGER DEFAULT 1,
    state TEXT DEFAULT 'IDLE',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    games_played INTEGER DEFAULT 0,
    total_won INTEGER DEFAULT 0,
    total_lost INTEGER DEFAULT 0,
    bankruptcy_count INTEGER DEFAULT 0,
    safe_balance INTEGER DEFAULT 0
);

-- Event history
CREATE TABLE IF NOT EXISTS event_history (
    event_id TEXT PRIMARY KEY,
    user_id INTEGER,
    event_type TEXT NOT NULL,
    amount INTEGER DEFAULT 0,
    metadata TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    chat_id INTEGER,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- AI credit sessions
CREATE TABLE IF NOT EXISTS ai_credit_sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER,
    status TEXT DEFAULT 'active',
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME,
    ai_score INTEGER,
    reward_amount INTEGER,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- AI dialogue messages
CREATE TABLE IF NOT EXISTS ai_dialogue_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES ai_credit_sessions (session_id)
);

-- User groups (for leaderboards)
CREATE TABLE IF NOT EXISTS user_groups (
    user_id INTEGER,
    chat_id INTEGER,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, chat_id),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_event_history_user_id ON event_history (user_id);
CREATE INDEX IF NOT EXISTS idx_event_history_created_at ON event_history (created_at);
CREATE INDEX IF NOT EXISTS idx_user_groups_chat_id ON user_groups (chat_id);

-- ============================================================
-- DOWNGRADE
-- ============================================================
-- To rollback (run manually if needed):
-- DROP INDEX IF EXISTS idx_user_groups_chat_id;
-- DROP INDEX IF EXISTS idx_event_history_created_at;
-- DROP INDEX IF EXISTS idx_event_history_user_id;
-- DROP TABLE IF EXISTS user_groups;
-- DROP TABLE IF EXISTS ai_dialogue_messages;
-- DROP TABLE IF EXISTS ai_credit_sessions;
-- DROP TABLE IF EXISTS event_history;
-- DROP TABLE IF EXISTS users;
