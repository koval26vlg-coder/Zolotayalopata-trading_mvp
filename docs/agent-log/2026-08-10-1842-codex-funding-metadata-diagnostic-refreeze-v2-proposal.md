# Funding metadata diagnostic refreeze v2 proposal

- Time: 2026-08-10 18:42 +03:00
- Base commit: `94842c538cbe4f35d8aacd03b05928955b5ac615`
- V1 remains terminal `STOPPED_INCOMPLETE`; retry, resume and receipt/output reuse are forbidden.
- Proposal hash: `3f247f93428e8b4e8cb340b3c1144e2b6bbeadc77bb9871e814b61a8bd5bfa75`
- Proposal file SHA-256: `0105b8afcf7dc9372d72dab4987b045baa5f62cf508f8193278803ad08ce8b3f`
- Exact preview patch SHA-256: `f116ab6695988402ea636f8f46b7de1f48a52c57f3b7734b0417c4efb4de9f47`
- Preview audit hash: `517112fd6c4853a83848cb4d0370c6c6975c63fa18bd60970ba60f4d65dfdde0`
- Preview audit file SHA-256: `bd2068646ac47224c02a2b25cb82b87e8523fc0709bbf5e61987bb2070652c88`

The first independent review rejected the preview because redirects could escape the endpoint/request contract and the diagnostic record was not validated strictly enough. The preview was rebuilt: redirects are rejected, diagnostic writes require exact fields and JSON types, and reads revalidate the canonical hash before the launcher can persist a safe summary. The second independent review returned `PASS`.

Verification in two isolated worktrees: 17/17 targeted tests, 99/99 funding tests, Ruff, `py_compile`, PowerShell parser and exact patch apply all pass. Unapproved preflight remains blocked with no HTTP request, output or failure record. The patch is not applied in the primary worktree; no receipt/runtime manifest was created and no network run occurred.

Next checkpoint: one exact hash-bound user approval is required before applying the patch, creating a new v2 receipt/runtime manifest or starting one visible metadata discovery run.
