# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Python 3.10 compatibility: `tomllib` fallback via `tomli` for `src/agentcost/budget.py` (#26)
- `--strict` flag on `agentcost analyze`: log parse failures exit non-zero instead of being reported as zero usage (#83)
- `agentcost forecast` command: projects future spend from recent daily usage (linear trend plus a day-of-week pattern, with an approximate 95% range) and exits 1 when projected spend exceeds `--budget` (#173)
- `agentcost forecast` command: projects future spend from recent daily usage (linear trend plus a day-of-week pattern, with an approximate 95% range) and exits 1 when projected spend exceeds `--budget` (#173)


### Fixed
- `alert` now treats spending equal to the threshold as within budget, matching `budget check` and SARIF findings (#189)
- A log that cannot be read faithfully now always says so. The shared reader distinguishes a latin-1 log (entries recovered, warning emitted) from a file that is not text at all, and a binary log no longer decodes as "UTF-16" on a two-byte guess and get reported as a faithful read while contributing zero usages. `--strict` now fails on a log that is not text, instead of reporting it as an empty session (#185)
- `budget set --quiet` (and `-q`) now suppresses per-period budget output while still saving the configured thresholds (#188)
- `ClaudeCodeParser`, `CodexParser`, `OpenCodeParser` and `HermesParser` no longer crash on UTF-16 or other non-UTF-8 logs: all five parsers now share one encoding-fallback reader, so one such file cannot abort a directory scan (#182)
- BOM-less UTF-16 logs (`utf-16-le` / `utf-16-be`) are now decoded by the shared encoding-fallback reader instead of being read as NUL-filled UTF-8 and silently yielding zero usages (#185)
- Logs that are not valid UTF-8 or UTF-16, such as latin-1 text, no longer crash a scan with `UnicodeError`. They are read with undecodable bytes replaced, still counted, and a warning says the read was not faithful (#185)
- CI failure on Python 3.10 due to missing `tomllib` stdlib module (#26)
- `CursorParser` no longer fails silently on unreadable log files: missing, oversized (>100MB), or non-UTF-8 logs print a warning to stderr and are skipped, so one broken file cannot mask the rest (#83)
