---
status: resolved
trigger: "Stage verification after switching provider=openrouter showed OpenRouter 401 Unauthorized; current code still logs sanitized error but generate_initial_greeting() returns hardcoded fallback for real-provider failure, so /credit appears to generate a task when LLM failed. Fix this."
created: 2026-05-10T02:30:00Z
updated: 2026-05-10T03:25:00Z
---

## Current Focus

hypothesis: Real-provider fallback masking fixed and verified.
test: Commit selected files and push branch.
expecting: Commit excludes untracked helper files and branch pushes cleanly.
next_action: archive debug session, commit, push

## Symptoms

expected: Non-mock `/credit` should fail visibly and clean up when LLM auth/network/model call fails.
actual: OpenRouter returned 401 Unauthorized but `generate_initial_greeting()` returned hardcoded fallback, making `/credit` look like it generated a task.
errors: OpenRouter 401 Unauthorized observed in stage verification (non-secret finding).
reproduction: Configure provider=openrouter with invalid/unauthorized key and trigger `/credit`.
started: TASK-022 stage verification.

## Eliminated


## Evidence

- timestamp: 2026-05-10T02:45:00Z
  checked: bot/services/ai.py
  found: generate_initial_greeting logs real-provider error type but then returns hardcoded fallback; generate_response logs error type but returns a fake completed grant; JSON parse failures also produce a default grant.
  implication: Real provider auth/network/model failures can look like successful AI output and even grant credit.
- timestamp: 2026-05-10T02:45:00Z
  checked: /credit handler tests and E2E smoke credit assertion
  found: Handler already has cleanup path for raised greeting errors; E2E only checks for fresh active credit session and does not explicitly reject known fallback reply text for non-mock providers.
  implication: Fix should be mainly AIClient raising plus tests; E2E can add an explicit guard against known fallback text.
- timestamp: 2026-05-10T03:00:00Z
  checked: patched AIClient and E2E smoke helper
  found: Added AIServiceError for real-provider failures, OpenAI client timeout, no fake response grants on provider/parse errors, and E2E guard rejecting known credit fallback text for non-mock ai.provider.
  implication: Stage OpenRouter 401 should now result in handler unavailable message and failed/closed session, not a fake task.
- timestamp: 2026-05-10T03:10:00Z
  checked: targeted tests
  found: ./scripts/test.sh tests/unit/test_ai_client.py tests/unit/test_ai_credit_handler.py tests/unit/test_telegram_e2e_smoke.py passed (57 passed, 6 warnings).
  implication: Focused behavior is verified; proceed to full validation.
- timestamp: 2026-05-10T03:25:00Z
  checked: full tests and lint
  found: ./scripts/test.sh passed (223 passed, 6 warnings); ./scripts/lint.sh passed with existing pyright warnings only.
  implication: Fix is verified.


## Resolution

root_cause: AIClient still handled real-provider failures as successful local fallbacks: greeting returned known fallback text and response returned fake completion_data, masking OpenRouter 401/auth and other provider errors.
fix: Added sanitized AIServiceError for real-provider greeting/response failures, removed fake real-provider fallbacks/grants, added bounded OpenAI client timeout, and added E2E guard to reject known credit fallback text for non-mock provider.
verification: Targeted AI/E2E tests passed (57 passed); full ./scripts/test.sh passed (223 passed); ./scripts/lint.sh passed.
files_changed: ["bot/services/ai.py", "tests/unit/test_ai_client.py", "scripts/telegram_e2e_smoke.py", "tests/unit/test_telegram_e2e_smoke.py"]
