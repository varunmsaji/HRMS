# Repository Organisation & Git Audit — 2026-11-28

Scope: the local checkout at `/media/varun/varun29/work/staff-spectrum/HRMS` (branch `test`, HEAD `87ccdf9`) —
folder layout, git configuration and history, repository hygiene, CI/branch workflow, and professional-readiness.
Method: read-only inspection (git plumbing, `ls`, `du`, file reads). Nothing was changed, staged or committed.
Limits: GitHub-side settings (branch protection, secrets, Dependabot config, required checks) were not inspected.

## 1. Verdict

| Area | Rating | One-line summary |
|---|---|---|
| Monorepo structure (`apps/`, `infra/`, `docs/`) | Good | Clear three-app split, sensible `infra/`, deep and mostly consistent docs. |
| Repository root | **Poor** | ~22 tracked files at root, several are clutter, binaries or stale notes. |
| Git workflow & guardrails | Good | `test`→`main` PR flow, CI gates, auto-merge, local pre-push hook, gitleaks. |
| Git history | Fair | Mostly Conventional Commits; 311 MB of `.next` cache once committed, 68 non-conventional subjects. |
| Secrets hygiene | Good | `.env*` ignored and never in history; scanner configured. One doc lists demo creds (dev-only). |
| Local disk hygiene | Fair | 3.8 GB of prod backups and 11 MB of design dumps sit inside the working tree (ignored, but risky). |
| OSS/professional metadata | **Poor** | No LICENSE, SECURITY, CONTRIBUTING, CODEOWNERS, PR template, or in-repo dependabot config. |

## 2. Findings (ranked)

### High

**H1. Production backups live inside the repo directory (3.8 GB).**
`backups/` holds Postgres dumps, `postgres_dumpall.sql.gz`, `redis_volume.tar.gz`, `server_config.tar.gz`, MinIO data, nginx
certs (`nginx_certs_systemd.tar.gz`) and production code tarballs. It is gitignored, so it cannot be committed by accident
through normal flow, but it sits one `git add -f`, one `zip`, one IDE upload, or one sync-tool run away from leaking — and
it likely contains real employee PII and TLS private keys. Recommendation: move to an encrypted location outside the repo
(e.g. `~/secure-backups/hrms/`), keep only a pointer doc in the repo. Treat as sensitive data under your own compliance rules.

**H2. Build cache history bloat: 612 blobs / 311 MB of `apps/web/.next/cache` in history.**
Committed in `6f0b128` and `e2e442d`, untracked in `e208144`. It is why `.git` is 124 MB (66 MB pack + 36 MB loose) for a
repo whose source is a fraction of that. Every fresh clone downloads it. Fixing needs a history rewrite
(`git filter-repo`), which AGENTS.md forbids for pushed history — so this is a **decision for the owner**, not something to
do casually. Pragmatic alternative: leave it, and run `git gc --prune=now` locally to compact the 5,500 loose objects.

**H3. Root `main` (local) is 109 commits behind `origin/main`.**
`git branch -vv`: local `main` at `ef93206`. Harmless while nobody works on it, but a stale `main` is a trap (wrong base for
a branch, misleading `git log main`). Recommendation: `git fetch && git branch -f main origin/main` (safe: you are on `test`).

### Medium

**M1. Repo root clutter (22 tracked files).** Items that do not belong at the root of a professional monorepo:

| File | Problem | Suggested home |
|---|---|---|
| `mavericks-kit.zip` (3.7 MB) | Binary archive tracked in git | remove from repo / external storage |
| `shirt.png`, `shorts.png` (1.9 MB each) | Unreferenced-looking images | `apps/*/assets` if used, else delete |
| `landing-page-code.md` (72 KB) | Code dump in markdown | `docs/design/` or delete |
| `pending task.md` | Space in filename; stale session note ("paused after Stage 4") | `docs/` or issue tracker |
| `MOBILE_UX_NEXT_STEPS.md` | Agent hand-off note | `docs/audits/` next to the audit it references |
| `run_full_tests.py` (27 KB) | Test orchestrator at root | `scripts/` |
| `dev.sh`, `start-web.sh`, `start-mobile.sh` | Three launchers at root plus `scripts/dev.sh` and `scripts/dev.py` — four overlapping entrypoints; `dev.sh` is only a shim to `scripts/dev.sh` | consolidate under `scripts/`; keep `npm run dev` |
| 4 compose files (`docker-compose.yml`, `.prod`, `.vps`, `.monitoring`) | Reasonable, but undocumented which is canonical (`.prod` vs `.vps`) | move non-default ones to `infra/compose/` or document in README |

**M2. Stray directories and spaced filenames at the root.**
`work done/` (tracked, space in name), `documents/` (partly tracked, partly ignored), `.dev-logs-start.log` / `.dev-logs/` (ignored),
`__pycache__/` and `test-results/` at root (ignored, leftover `run_full_tests.py` output). Files with spaces in tracked
paths: 6 (`work done/…`, `pending task.md`, `apps/web/Krewoxa landing page system/*`, two PDFs in `docs/archive/source-pdfs/`).
Spaces break shell scripts and some tooling; rename to kebab-case.

**M3. Design-tool dump `stitch_hrms_employer_decision_dashboard (1)/` (11 MB, ignored).**
A browser-download duplicate suffix `(1)`. Ignored via glob so it is not a git problem, but it is clutter in the project
folder. Move to a design-assets location outside the repo, or archive.

**M4. Duplicate / near-duplicate docs trees.**
- `docs/audit/` (6 files, DB-focused) vs `docs/audits/` (142 files) — two directories, one purpose.
- `docs/tutorila/` (typo of "tutorial", untracked, 26 files) and `docs/engineering-handbook/` (untracked) have **identical
  numbered file names** (`00-START-HERE.md`, `01-APPLICATION-OVERVIEW.md` …). This looks like a rename/copy in progress.
  Left alone per AGENTS.md (changes you may be mid-way through); decide on one, delete the other.
- `docs/testing/` is 225 tracked files including `qa_evidence_*/tracked_diff_start.patch` (≈ 0.5 MB each) — evidence
  artefacts that belong in release assets or an archive, not the working docs tree.
- 142 audit files in one flat folder with no index; date-stamped names help, but there is no `README.md` listing them.

**M5. Large binaries tracked in git.** `apps/api/models/liveness/*.onnx` + `.caffemodel` (≈ 7 MB total),
`docs/api/openapi.json` (1.7 MB, generated), `docs/api/postman/…json` (340 KB, generated). Models are fine if pinned, but
consider Git LFS or a model-download step; generated API docs should be CI artefacts, not hand-committed. Note
`apps/api/models/face/opensource-v1/*.onnx` is ignored, so model handling is already inconsistent between the two.

**M6. Missing repository-standard files.** No `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `.github/CODEOWNERS`,
`.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/`, or `.github/dependabot.yml` (yet Dependabot branches exist,
so it is configured in repo settings — invisible to code review). `CODEOWNERS` is especially valuable here: it would formalise
the "a person must merge `.github/`, migrations, AGENTS.md" rule that is currently enforced only inside the auto-merge script.

**M7. Stale remote branches (7).** `origin/claude/tender-gauss-5xrf9z` (2026-11-10, already merged into `main`) can be
deleted. Three Dependabot branches are open since 2026-11-26 (`filelock`, `mako`, `virtualenv`) plus one npm group — review or close them.

### Low

**L1. Commit-message discipline.** 560 commits: 262 `feat`, 117 `fix`, 54 `docs`, 28 `test`, 16 `chore`, 7 `ci`, … but
**68 (12%) are not Conventional Commits**, e.g. `till shift assignement done, starting on compensation`,
`base done now movint to system design`, `foundation done front end needs more work keep for later`. Recent history is clean;
the offenders are old. Enforce with a `commit-msg` hook or a PR-title check going forward. Typos in two of them.

**L2. Author identity split.** `varun` (503) and `varun saji` (12) — same email, two names. Add a `.mailmap` to unify
`git shortlog` / blame output. `Claude <noreply@anthropic.com>` (7) and `github-actions[bot]` (38) are expected.

**L3. Line-ending / attribute config.** No `.gitattributes`. Index shows 4 CRLF files, 1 mixed, 166 `-text` (binary).
`.editorconfig` mandates LF, so add `* text=auto eol=lf` plus explicit binary patterns to enforce it.

**L4. `.claude/launch.json` is tracked** while the rest of `.claude/` is ignored. Acceptable if intentional (shared run
config), but document it. `.claude/worktrees/` is empty and `scheduled_tasks.lock` is a stale lock from 2026-09-27.

**L5. Hooks are local-only.** Only one hook exists (`pre-push`, blocks pushes to `main`), and it is not versioned. A fresh
clone has no guard. Move to `.githooks/` with `git config core.hooksPath .githooks` (documented in README), or rely on GitHub
branch protection — verify that is enabled on `main` (not inspectable from here).

**L6. README drift.** The "Repo layout (target — Document 06)" block lists `apps/api` and `apps/web` only — `apps/mobile`
(1,228 tracked files, the largest app) and `scripts/`, `documents/` are missing. "Scaffold status … Sprint 0" is out of date.
Root `package.json` is named `hrms-platform` v0.1.0 and only wraps scripts (fine, but there is no workspace definition).

**L7. Four copies of `.env`-style files on disk** (`.env`, `apps/.env`, `apps/api/.env`, `apps/web/.env.local`): all
ignored, all mode `664` (world-readable). `chmod 600` them. The `apps/.env` file looks accidental.

**L8. Local build output** (not a repo problem, a disk-hygiene one): `apps/web/node_modules` 641 MB, `apps/api/.venv` 542 MB,
`apps/mobile/build`, `.next`, `.next-e2e`, `.mypy_cache`, `.ruff_cache` ×3 versions. All ignored; clean periodically.

## 3. What is already good

- **Branch model is explicit and enforced**: `main` release-only, `test` working branch, PR-only path, documented in `AGENTS.md`, backed by a local pre-push hook and an auto-merge workflow that fails closed and excludes sensitive paths.
- **CI is comprehensive**: six jobs (`api`, `migrations`, `web`, `mobile`, `security-scan`, `dependency-scan`), pinned to UTC, mobile contract fixtures verified against API schemas, import-boundary linting (`.importlinter`).
- **Secret hygiene**: `.env*` never appeared in history (`git log --all -- .env` is empty); gitleaks config uses narrow, per-file, justified allowlists rather than blanket disables.
- **Clean separation of apps**, each with its own Dockerfile / lockfile (`uv.lock`, `package-lock.json`, `pubspec.lock`) and README or AGENTS file.
- **Docs are extensive and cross-linked** (ADRs, business rules, product spec, runbooks, QA registers).
- **Linear-enough history**: 63 merge commits, all through PRs; no force-push evidence; `origin/test` is level with local `test`.
- **`.editorconfig`** present; `.gitignore` is well commented and covers Python, Node, Flutter, Docker, local logs.

## 4. Current working tree (not mine — left untouched)

12 modified files (shift module: API schedule/organisation + web shift components) and 20+ untracked files (shift audit
docs, `label.ts` + tests, `test_shift_draft_concurrency.py`, `docs/engineering-handbook/`, `docs/tutorila/`). 670 insertions /
53 deletions uncommitted. Per AGENTS.md these are someone's in-progress work; stage by name when committing.

## 5. Recommended action plan

**Do now (safe, no history changes)**
1. Move `backups/` out of the repo to encrypted storage; `chmod 600` the four `.env` files.
2. `git fetch origin && git branch -f main origin/main` (local-only, you are on `test`).
3. Decide `docs/tutorila` vs `docs/engineering-handbook` and remove the loser; merge `docs/audit/` into `docs/audits/`.
4. Delete merged remote branch `claude/tender-gauss-5xrf9z`; triage the 4 Dependabot branches.
5. Run `git gc` to compact loose objects.

**Next PR (one tidy commit: `chore: tidy repository root`)** — touches no `.github/`, so it can auto-merge
1. Remove `mavericks-kit.zip`, `shirt.png`, `shorts.png`; relocate `landing-page-code.md`, `pending task.md`, `MOBILE_UX_NEXT_STEPS.md`, `run_full_tests.py`, `work done/`.
2. Collapse `dev.sh` / `start-*.sh` into `scripts/`; update `package.json` and README.
3. Add `.gitattributes`, `.mailmap`, `docs/audits/README.md` (index), refresh README layout block and add `apps/mobile`.
4. Rename space-containing paths to kebab-case.

**Needs a person to merge (touches `.github/`)**
5. Add `CODEOWNERS`, `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml`, and a PR-title Conventional Commits check.
6. Add `LICENSE` (or an explicit proprietary notice), `SECURITY.md`, `CONTRIBUTING.md` (can be a short pointer to AGENTS.md).
7. Move the pre-push hook to a versioned `.githooks/` directory.

**Owner decision**
8. History rewrite to purge 311 MB of `.next` cache — only worthwhile if clone size matters; requires coordinated re-clone and breaks AGENTS.md's no-rewrite rule, so do it deliberately or not at all.
9. Git LFS for ONNX/caffemodel weights.

## 6. Evidence snapshot

- Commits: 560 (63 merges). Authors: varun 503, github-actions[bot] 38, varun saji 12, Claude 7.
- Tracked files: 3,914 — mobile 1,228 · api 1,015 · web 752 · docs ≈ 800.
- `.git`: 124 MB (pack 66.5 MB + 35.6 MB loose / 5,500 objects).
- Disk: apps 4.7 GB (node_modules 641 MB, .venv 542 MB), backups 3.8 GB, docs 34 MB.
- Branches: local `main` (behind 109), `test`; remote `main`, `test`, 1 claude branch, 4 dependabot branches. `origin/test` is 36 commits ahead of `origin/main` (normal while a PR is pending or between merge cycles).
