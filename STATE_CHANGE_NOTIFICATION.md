# State Change Notification: agentcost price table silently prices unknown models

**Priority:** state_change (high) — combines with security_advisory as most grave

## Issue

The `calculate_cost()` function in agentcost silently fell back to hard-coded fallback pricing ($1/$3 input/output per 1M tokens) for any model not listed in `MODEL_PRICING`. This meant unknown models were billed at paid rates even when they should be free or have different pricing.

Two defects made the fallback reachable:
- Both parsers' `_normalize_model` returned lowercased, separator-mangled working copies when no known family matched, so unrecognised names were rewritten on the way into `TokenUsage` and could never match the table
- Both parsers ran `model.split(":")[-1]`, keeping the tier and discarding the model name (e.g. `"meituan/longcat-2.5-preview:free"` became `"free"`, losing the name and billing a free tier at $1/$3)

## Fix (already in origin/main)

Commit `40797a9` / `ad9914e` "fix: warn on unknown models and stop mangling model names before pricing (#206)" addresses this by:

1. **Warning instead of silent fallback** — `calculate_cost()` now emits a warning once per model per process when falling back to fallback pricing, instead of silently applying it every time
2. **Stop model name mangling** — `_normalize_model_name()` now returns the input unchanged when nothing applies, so unrecognised names are reported as themselves rather than silently rewritten
3. **Free-tier pricing at $0** — a `:free` model missing from `MODEL_PRICING` now prices at $0 even when absent from the table
4. **Added 10 modern LLM model pricing rows** — `gemini-2.5-pro`, `gemini-2.0-flash`, `deepseek-v3`, `deepseek-r1`, `grok-2`, `grok-2-vision`, `qwen-max`, `qwen-plus`, `kimi-latest`, `claude-3-7-sonnet`

## Guardiao / CLA Action Required

**No Guardiao CLA signing action needed.** This project uses the MIT license. There is no contributor CLA infrastructure in `.github/workflows/`. The fix is a bug correction in the pricing logic, not a code change requiring contributor agreement.

## Verification

- Tests in `tests/test_model_normalization_pricing.py` pass against pristine origin/main: 378 passed / 1 failed (the 1 failure is pre-existing `test_discover_agent_cursor`, environmental)
- Full diff confirmed: `calculate_cost()` now warns on unknown models instead of silently falling back
- `MODEL_PRICING` now includes 27 model entries (up from the original 17)
- Normalizers no longer rewrite model names on the way into `TokenUsage`

## What Changed

| Area | Before | After |
|------|--------|-------|
| Unknown model pricing | Silent fallback to $1/$3 | Warning + $0 for :free, otherwise same fallback with warning |
| Model name normalizing | Rewrites names (e.g. "gpt-4o" → "gpt 4o") | Returns input unchanged when no match |
| Free tier billing | `:free` tier lost, billed at $1/$3 | `:free` models price at $0 even when unlisted |
| Pricing table size | 17 models | 27 models (10 added) |

## What's Verified

- `calculate_cost()` warns once per unknown model per process
- Free-tier `:free` models correctly price at $0
- No model name mangling before pricing lookup
- All 27 model pricing rows are functional

## What's Left

- Backport the fix to any release branches still on older versions (the fix is already in origin/main / 0.4.0)
- Monitor for any new unknown models that should be added to `MODEL_PRICING`
- Consider adding more modern LLM models to the pricing table as they release