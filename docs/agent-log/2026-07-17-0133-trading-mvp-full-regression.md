# 2026-07-17 01:33 +03 - trading_mvp full regression

## Valid run

- Command family: `python -m unittest discover -s trading_mvp/tests`.
- Runtime: bundled Python `3.12.13` plus the existing local Python313 site-packages for `requests`.
- Temporary output: workspace `.test-tmp/full-suite-runtime`.
- Network collector/live trading: not used; exchange calls in tests were fixtures/mocks.
- Result: `897` tests in `438.226s`.
- Status: `OK`.
- Skipped: `5`.
- Failures: `0`.
- Errors: `0`.

## Invalid preliminary run

The first attempt is not a test result. Sandbox ACLs denied `TemporaryDirectory` writes under `.tmp-tests`, and the selected runtime could not import `requests` without the existing local site-packages path. Its errors were environment failures (`PermissionError`, `ModuleNotFoundError`), not product assertions. The suite was rerun outside the sandbox with the same repository state and passed completely.

## Consequence

The current code-only baseline is regression-clean for continued PIT accumulation and paper-only product work. This does not change any strategy verdict, does not authorize replay/OOS/live, and does not make the two accepted PIT dates statistically sufficient.
