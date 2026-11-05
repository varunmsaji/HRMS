# Working in this repository

These rules apply to every AI agent and every person working here.

## Branches

- `main` is the release branch. Nobody commits or pushes to it directly.
- `test` is the working branch. All edits happen here.
- Changes reach `main` only through a pull request from `test`.

## Before you start

1. Run `git status` and `git branch --show-current`. If you are not on `test`, switch to it.
2. Run `git pull --ff-only origin test`.
3. If the working tree has changes you did not make, leave them alone and tell the user.
   Another agent or the user may be in the middle of something.

## While you work

- Stage files by name. Do not use `git add .` or `git add -A`, which can pick up someone else's work.
- Pull again before you push. If `test` has moved, integrate the new commits and rerun the checks.
- Never force-push, and never rewrite history that has been pushed.
- Never skip or weaken a check (tests, lint, the secret scan) to get a build passing. If that seems
  necessary, ask the user first.

## Getting a change into `main`

1. Run the checks for the apps you changed. See `.github/workflows/ci.yml` for the commands.
2. Push `test` and open a pull request from `test` to `main`, or update the one already open.
3. Report the CI result to the user, including any failures.
4. Do not merge until the user says so. Approval for one pull request does not carry over to the next.
5. Merge with a merge commit (`gh pr merge --merge`). Do not squash or rebase: that makes `test` and
   `main` drift apart and causes false conflicts on the next pull request.
6. After the merge, bring `test` back in line:

   ```bash
   git checkout test
   git pull --ff-only origin test
   git merge --ff-only origin/main
   git push origin test
   ```

Do not delete `test`.

## Other instructions

Files such as `apps/web/AGENTS.md` add rules for that part of the codebase and apply as well.
