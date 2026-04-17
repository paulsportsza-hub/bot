# DEV-STANDARDS.md — MzansiEdge Development Standards

Covers dispatch format, report protocol, and parallel-wave hygiene.
Authority order: `CLAUDE.md` → this file → `CODEX.md` → brief.

---

## §Dispatch Format v4

Every brief dispatched to an executor agent must include the following blocks in
order. Blocks marked **required** must be present; the brief is malformed without
them.

### Required blocks

```
# <BRIEF-ID> — <one-line title>

**Dispatched:** YYYY-MM-DD · **Depends on:** <BRIEF-ID or "none">

## Goal
[One paragraph. What changes, why it matters.]

## Files Owned
[Required. List every file path the agent is authorised to modify or create.
 Wildcards are allowed only for generated artefacts (e.g. reports/*.md).
 The agent must NOT touch files outside this list without filing a
 scope-expansion note (see §Agent Report Protocol).]

## Acceptance Criteria
[Bulleted. Each item must be binary — done or not done.]

## Investigation Before Build
[Optional. Steps the agent must complete before writing code.]

## Out of Scope
[Explicit exclusions to prevent scope creep.]

## Report Filing
[Notion database, data_source_id, title format, required fields.]

## Non-negotiables
[SO references and locked rules that apply to this brief.]
```

### Files Owned — rules

- Each path must be resolvable from the repo root.
- If a brief covers a whole directory, list it explicitly (e.g. `ops/`), not
  with a bare wildcard.
- An agent that discovers it needs an additional file must STOP, file a
  scope-expansion note, and wait for a revised brief unless the brief already
  grants blanket approval for a directory.
- "Wide" staging commands (`git add -A`, `git add .`) are **banned** in
  parallel-wave contexts. Stage only the files listed in Files Owned.

---

## §Agent Report Protocol

Every executor report must include the following sections.

### Required sections

```
# <BRIEF-ID> — <outcome>

**Agent:** <model>
**Wave:** <BRIEF-ID>
**Project:** MzansiEdge
**Date:** YYYY-MM-DD
**Status:** Complete | Blocked | Partial

## Summary
[What changed and why.]

## Verification
[Commands run and their output. Never claim a fix works without this.]

## Diff-stat (required when wave has >1 parallel brief)
Paste the output of:
  git diff --stat <SHA>~1..<SHA>
Confirm: "Only declared files appear — no scope leakage."
If out-of-scope files appear, file a scope-expansion note below.

## Scope-expansion note (if applicable)
[Required if commit contains files outside the brief's Files Owned list.
 State which files, why they were necessary, and what approval covered it.]

## CLAUDE.md Updates
[List required constitutional or repo-reference updates, or "None".]
```

### Diff-stat rule

- When a wave has **more than one parallel brief**, every executor report
  **must** include the `git diff --stat` block above with the commit SHA.
- For single-brief waves the diff-stat is recommended but not required.
- A report without a SHA in a multi-brief wave must be marked
  `Work-in-tree, unverified` — not `Complete`.

---

## §Parallel-Wave Hygiene

Rules that apply whenever two or more briefs are dispatched in the same wave.

1. **File-set isolation.** Each agent stages ONLY the files listed in its
   brief's Files Owned block. No brief may assume ownership of a file
   declared by another brief in the same wave.

2. **No wide staging.** `git add -A` and `git add .` are banned. Use
   `git add <file1> <file2> …` with the exact paths from Files Owned.

3. **Commit verification.** After each commit, run
   `git diff --stat HEAD~1..HEAD` and confirm the set matches Files Owned.
   If it does not, amend before pushing (only if not yet shared) or file a
   scope-expansion note.

4. **Attribution accountability.** Accidental cross-contamination of another
   brief's files is a process failure. The agent that made the wide-add must
   document it in the report. Retroactive rewriting of git history is out of
   scope; log-only.

---

## §Report Filing (SO #35)

- File all reports via `scripts/push_report.py` using `NOTION_REPORTS_DB` from
  `.env`. Never use the Notion MCP tools.
- Title format: `<BRIEF-ID> — <outcome>`
- Required fields: Status, Wave, Agent, Project, Date.
- **When wave has >1 parallel brief:** report must include a diff-stat block
  (see §Agent Report Protocol above).
- Pre-file verification: confirm the target database name equals
  `📋 Agent Reports Pipeline` exactly. If it does not, abort and re-read SO #35.
