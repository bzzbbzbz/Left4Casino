---
status: resolved
trigger: "Work in /root/n8n-install/python-runner on current branch feature/task-021-event-e2e-no-start. The user reports a bug: /credit replies with fallback text instead of generating a task via LLM. Diagnose and fix root cause. Do not read/print secrets, tokens, settings.toml, .env, or production config values. Do not touch production, /opt stage runtime, DBs, or untracked credential helper files."
created: 2026-05-10T00:00:00Z
updated: 2026-05-10T01:00:00Z
---

## Current Focus

hypothesis: Root cause fixed and verified.
test: Archive debug session and commit/push branch.
expecting: Commit contains only TASK-022 code/tests/docs/debug changes, excluding untracked credential helpers.
next_action: git status, commit selected files, push branch

## Symptoms

expected: /credit should use configured OpenAI/OpenRouter LLM to generate an assignment greeting when valid API key/config is available.
actual: /credit replies with fallback text instead of generating a task via LLM.
errors: No explicit error reported.
reproduction: Trigger /credit with an eligible user (balance <= 0, no active session, cooldown passed).
started: Unknown.

## Eliminated


## Evidence

- timestamp: 2026-05-10T00:05:00Z
  checked: bot/handlers/ai_credit.py
  found: /credit calls ai_client.generate_initial_greeting(), stores/sends returned string, and only sends handler fallback if generate_initial_greeting raises.
  implication: If user sees the generic assignment fallback "Эй, ты! Хочешь денег? Удиви меня!", it is produced inside AIClient, not by the handler exception path.
- timestamp: 2026-05-10T00:05:00Z
  checked: bot/services/ai.py
  found: AIClient.__init__ ignores config.provider and chooses OpenRouter solely from OPENROUTER_API_KEY; generate_initial_greeting catches all exceptions and returns a hardcoded fallback string.
  implication: Real OpenAI/OpenRouter failures are masked as successful fallback greetings, and provider semantics are not explicit.
- timestamp: 2026-05-10T00:05:00Z
  checked: bot/config_reader.py
  found: AIConfig defaults provider to "mock" and api_key to "dummy" but has no validation/normalization tying provider to key availability.
  implication: Missing [ai] config or unset key can silently produce dummy real-client initialization plus internal fallback.
- timestamp: 2026-05-10T00:15:00Z
  checked: bot/__main__.py
  found: Startup injects one AIClient(ai_config) into Dispatcher and /credit receives that instance; no handler-level mock substitution exists.
  implication: The root behavior is in AIClient construction/generation, not dependency injection.
- timestamp: 2026-05-10T00:25:00Z
  checked: bot/services/ai.py and new tests
  found: Implemented provider-aware AIClient: mock returns local fallback without client, openrouter always sets OpenRouter base_url from provider, openai uses OpenAI endpoint/key, missing/dummy real keys fail at startup without printing secrets.
  implication: A configured real provider with valid key should now call the LLM path instead of accidental mock/fallback path.
- timestamp: 2026-05-10T00:35:00Z
  checked: targeted tests via ./scripts/test.sh tests/unit/test_ai_client.py tests/unit/test_ai_credit_handler.py
  found: 4 passed; no live network used.
  implication: Provider routing, fallback boundaries, and /credit generated greeting behavior are covered.
- timestamp: 2026-05-10T00:45:00Z
  checked: ./scripts/test.sh and ./scripts/lint.sh
  found: Full test suite passed (206 passed, 6 warnings). Lint failed only because tests/unit/test_ai_client.py needed ruff formatting.
  implication: Functional verification is green; fix formatting before final validation.
- timestamp: 2026-05-10T01:00:00Z
  checked: ruff format, ./scripts/lint.sh, and targeted tests after formatting
  found: Lint passed (ruff + pyright, existing warnings only); targeted AI tests passed again (4 passed). Full suite had already passed before formatting.
  implication: Fix is verified without live network; formatting did not change behavior.


## Resolution

root_cause: AIClient ignored ai.provider for endpoint selection and only enabled OpenRouter when OPENROUTER_API_KEY existed; OpenRouter keys supplied through config were sent to the default OpenAI endpoint, and generate_initial_greeting swallowed the resulting exception as a successful hardcoded fallback.
fix: Make AIClient provider-aware: explicit mock never constructs/calls LLM; openrouter always uses OpenRouter base_url with env-or-config key; openai uses OpenAI key/endpoint; real providers reject missing/dummy keys without exposing secrets. Added targeted tests for routing, fallback, and /credit reply behavior.
verification: Targeted AI tests passed before and after formatting; full ./scripts/test.sh passed (206 passed); ./scripts/lint.sh passed.
files_changed: ["bot/services/ai.py", "tests/unit/test_ai_client.py", "tests/unit/test_ai_credit_handler.py", "docs/specs/archive/TASK-022_CREDIT_LLM_FALLBACK.md", "status.yaml", "logs/dev_diary.md"]
