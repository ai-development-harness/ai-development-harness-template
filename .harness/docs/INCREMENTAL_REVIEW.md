# Incremental FIX Review and Verification Continuation

## Purpose

A first `STEP REVIEW` remains a full independent semantic review. After a
successful `STEP FIX`, a subsequent `STEP REVIEW` must **close only the
previous confirmed findings and check direct regressions of that FIX**.
Independent security/test reviewers retain their mandatory gates, but receive
the same scoped patch. A pre-existing issue in untouched behavior is reported
separately and does not silently expand the current repair cycle.

## Durable exact baseline

`.harness/tools/fix_delta.py` captures a Git **tree** before the semantic FIX
starts, using an alternate temporary index. The ordinary index/worktree is not
modified. Tracked staged/unstaged and non-ignored untracked content are
represented in the tree; Git-ignored local/secrets content is excluded. The
tree object remains available in local Git object storage until normal GC. Do
not run Git garbage collection between a FIX and its corresponding REVIEW.

Local metadata:

```text
.harness/local/execution/fix-delta/STEP-NNN.json
.harness/local/execution/fix-delta/STEP-NNN.patch
```

These files are operational, untracked, not project evidence. They are bound to
the exact FIX execution ID, the source immutable FAIL report, findings'
fingerprints, pre-FIX tree, and post-FIX subject revision. Restart/resume of
the **same** FIX must not replace its initial snapshot. A new FIX refreshes it.

`fixReview` in the canonical reviewer handoff:

- `mode=initial`: no completed FIX delta, run ordinary full review.
- `mode=fix_delta`: inspect source report, previous fingerprints, exact patch,
  and affected tests/direct behavior. Read neighboring code only when needed
  to understand the changes, not to reopen a whole-system audit.
- `mode=full_explicit`: a new full audit **requested by the user**. The invoking
  process must set `HARNESS_REVIEW_FULL=1` at `harness-dispatch.py start`.
  This override is persisted across separate writer processes.

A stale post-FIX subject, lost baseline Git tree, malformed local state or
oversized patch is a **blocker**, not permission to silently widen review.
Patch files are bounded to 1 MiB; pathological diffs require separate
resolution.

## Guarding new findings

For `fix_delta`, the canonical writer compares submitted fingerprints with
those of the prior FAIL review. A persisting original finding may remain.
Each genuinely new finding must be located on a changed path and must provide
`fixDeltaCausality: {"F-NNN": "concrete causal evidence linking the FIX change
to the observed regression"}` in the semantic-writer JSON payload.
A matching filename alone is not evidence; the reviewer must establish the
actual changed operation and result through Evidence Gate. The writer checks
the bounded structural contract; semantic truth still requires independent
reviewer judgment. Unconfirmed hypotheses never become findings.

Successful report publication consumes the local delta state. Historical
immutable reports and the original full implementation baseline remain
unchanged. This is deliberately **not** a replacement for Completion Gate,
plan freshness, specialized review, or Verification gates.

## Automated Verification manual continuation

`.harness/tools/verification_resume.py` retains the command-level PASS
result only if the aggregate Verification is `MANUAL_REQUIRED`. When explicit
manual or real-product observations arrive, automated results can be
reused *only* if all guards match:

- exact STEP ID and Verification contract basis;
- subject Git+worktree revision excluding generated STEP evidence;
- exact command list/order, timeout, Python and relevant executable/environment
  identity;
- every command previously PASS with exit code zero;
- recorded evidence age <= 30 minutes;
- no excluded high-risk STEP flags (`external-integration`,
  `security-sensitive`, `data-migration`, `destructive`,
  `release-critical`).

A changed input, FAIL, expired result, unknown executable identity or malformed
cache is a cache miss and runs the commands normally. The cache is deleted after
an aggregate PASS/FAIL. No external/integration result is reused by default.
This is **manual-stage continuation**, not a global test-result cache.

## Further incremental work

Context Contracts, Codebase Grounding and Semantic Blast Radius retain their
existing exact-input freshness rules; reviewers should reuse valid bounded
results rather than reconstruct unrelated architecture. Arbitrary test
selection by filenames or untrusted model guesses is **not authorized**:
selective checks require an explicit verified dependency-to-test map and must
fall back to full Verification when coverage is uncertain. Security preflight,
completion and freshness gates are never skipped based on LLM memory.

## Release checks

Run `python3 .harness/tools/run-self-tests.py` and
`python3 .harness/tools/validate.py --mode ci`. Regression must cover:

- original/persisted/closed findings, in-delta regression and outside finding;
- dirty/staged/untracked baselines, replay of the same FIX and stale subjects;
- manual continuation reuse, changed subject, contract, environment and
  timeout invalidation; no reuse after FAIL or in high-risk STEPs;
- required reviewer symmetry and full explicit override.
