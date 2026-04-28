# BUILD-RUNNER-DEMO-01 — runner demo marker

Synthetic marker for the dispatch_runner.sh AC-WAVE-3 demonstration of
BUILD-WORKTREE-DISPATCH-RUNNER-01. Created manually in the carve-out
(ops/) so the wave guard does NOT need to be bypassed; the runner is
then exercised in DISPATCH_RUNNER_TEST_MODE=1 to validate the full
pipeline (Notion fetch, status check, worktree create, SO #41 verify,
status update, prune) against a real commit on origin/main.
