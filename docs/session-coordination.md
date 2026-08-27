# Working the same repo with many sessions

Multiple Claude sessions build MapleGuard in parallel. Without rules they collide on the shared `main` checkout and branch pointers. These are the rules. They exist because we hit each failure below for real.

## Roles
- **Orchestrator** — exactly one session (the light-context coordinator). It OWNS `main`: it is the only session that checks out `main`, merges, and pushes. It does not do heavy builds.
- **Builders** — every other session. Each does one scoped task on its own branch, in its own worktree, and never touches `main`.

## The rules

1. **One owner of `main`.** Only the orchestrator checks out, commits to, merges into, or pushes `main`. No builder ever runs `git checkout main` in a shared working directory or commits onto `main`.

2. **Each builder = its own worktree + its own branch.** Spawned tasks run in an isolated git worktree (`.claude/worktrees/…`). Stay in it. Branch `claude/<task>` off `main`. Worktrees isolate the working tree, so branch switches never collide. Never create or switch a branch inside the orchestrator's main checkout.

3. **Builders never merge.** A builder commits + pushes its branch and reports: **branch name, HEAD sha, test count, open decisions**. The orchestrator merges.

4. **Sync before you build, merge often.** A builder runs `git merge origin/main` (or rebase) into its branch before starting, so it builds on current work. The orchestrator merges finished branches promptly to limit drift.

5. **Orchestrator hygiene (every commit/push):**
   - Verify `git branch --show-current` is `main` BEFORE any commit or push. (Commits have silently landed on the wrong branch when this was skipped.)
   - Merge one branch at a time: merge → run the full suite → push → verify `origin/main` actually advanced (`git log --oneline -1 origin/main`).
   - Update `TODO.md` after every merge.

6. **Untracked deliverables live in the main checkout.** Design files, docs, diagrams, and blogs written by a builder or the orchestrator into the main working tree are committed by the orchestrator (a builder's worktree cannot see them).

7. **Keep branches small and single-purpose.** One task, one branch. Easier to merge, easier to reason about.

## If a session's shell loses filesystem access
An "Operation not permitted" / `getcwd` failure on the repo volume is usually the shell process caching a permission state (e.g. after the drive's access is (re)granted). File reads may still work while `git` cannot. The fix is a **fresh process**: restart that Claude Code session. Do not fight it with retries — reads can sneak through while `git` never will.

## Shared context
Every session reads `ARCHITECTURE.md` first (the thesis, module map, trust rules), then this file, then its scoped task.
