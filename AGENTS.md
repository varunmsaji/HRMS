# Working in this repository

These rules apply to every AI agent and every person working here.

## Branches

- `main` is the release branch. Nobody commits or pushes to it directly.
- `test` is the working branch. All edits happen here.
- Changes reach `main` only through a pull request from `test`.
- A push to `main` from this machine is refused by a local git hook. Do not bypass it.

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
   CI runs on every push while the pull request is open.
3. When CI passes on the latest commit, `.github/workflows/auto-merge.yml` merges the pull request and
   brings `test` level with `main`. Do not merge it yourself.
4. If CI fails, fix the cause on `test` and push again. Report the failure to the user if you cannot
   fix it.
5. After the merge, run `git pull --ff-only origin test` before starting anything new.

### Changes a person must merge

CI passing does not merge a pull request that changes any of these, because they can weaken the checks
or are hard to undo. Tell the user it is waiting for them, and never merge it yourself:

- `.github/`
- `.gitleaks.toml`
- `AGENTS.md` and `CLAUDE.md`
- `apps/api/alembic/` (database migrations)

The user merges with a merge commit (`gh pr merge --merge`), not squash or rebase, which make `test`
and `main` drift apart. Then bring `test` level:

```bash
git checkout test
git pull --ff-only origin test
git merge --ff-only origin/main
git push origin test
```

### Passing CI is not the same as ready to release

CI does not click through the web app or run the mobile app on a device. Merging to `main` does not
deploy anything, and it must stay that way: the user tries the app before releasing it.

Do not delete `test`.

## Other instructions

Files such as `apps/web/AGENTS.md` add rules for that part of the codebase and apply as well.
