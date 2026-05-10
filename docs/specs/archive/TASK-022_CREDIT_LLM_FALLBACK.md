# TASK-022 — Fix `/credit` LLM greeting fallback

## Status

SPEC_READY

## Problem

`/credit` can reply with the hardcoded fallback greeting instead of an LLM-generated assignment even when AI is configured for OpenAI/OpenRouter.

## Requirements

- REQ-022-1: For `ai.provider = "openrouter"`, AIClient must use the OpenRouter-compatible endpoint whether the key comes from `OPENROUTER_API_KEY` or from `[ai].api_key`.
- REQ-022-2: For `ai.provider = "openai"`, AIClient must use the OpenAI endpoint and key from `OPENAI_API_KEY` or `[ai].api_key`.
- REQ-022-3: Explicit `ai.provider = "mock"` may return deterministic/local fallback text without network calls.
- REQ-022-4: Real LLM call errors may fall back safely, but must not expose secrets in logs.
- REQ-022-5: `/credit` must send the generated greeting returned by AIClient and not replace it with fallback text when AIClient succeeds.

## Acceptance Criteria

- Unit tests cover provider-specific greeting path without live network.
- Unit/integration tests cover mock/error fallback boundaries.
- Handler test proves `/credit` sends the generated greeting from AIClient.
- `./scripts/lint.sh` passes; targeted tests pass.

## Non-Goals

- No live OpenAI/OpenRouter calls in tests.
- No reading or printing production secrets, `settings.toml`, `.env`, DB files, or runtime configs.
