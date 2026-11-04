# Deploying web (landing page / frontend) changes to the Hostinger VPS

Audience: an AI coding assistant (or a person) asked to push a **web frontend change** (landing page, images, CSS, React code) to production at https://www.krewoxa.com. Everything here was verified on 2026-11-04 by doing two real deploys (hero penguin removal, ID-card "K" logo fix). Re-verify anything marked CHECK before relying on it.

This is not the full-stack release process. For API, migrations or database work use `HOSTINGER_DEPLOYMENT_RUNBOOK.md` and `PRODUCTION_DEPLOYMENT.md`.

## 0. Hard rules (the owner stated these)

1. **Hirico is a different app on the same server. Never touch it.** Its containers are `hirico-db` and `hirico-redis`, its files live in `/root/hirico`, its nginx site is `/etc/nginx/sites-enabled/hirico`, and its volumes are `hirico_*`. Do not edit, restart, rebuild, prune or delete anything of Hirico's.
2. **Never delete files on the server.** Add backups, overwrite only the exact files being changed. No `rm`, no `docker system prune`, no `docker compose down -v`, no `docker volume rm`.
3. **Only rebuild and restart the `web` service.** Always `up -d --no-deps web`. Do not restart api, worker, beat, postgres, redis, minio or nginx.
4. Do not edit anything else on the server (nginx config, `.env`, compose files, certificates). Do not print or copy `.env` contents; they hold secrets.
5. Never run a deploy that was not asked for. Tell the owner what will change and the downtime (a few seconds) before doing it.

## 1. Server facts

| Item | Value |
|---|---|
| Host | Hostinger VPS, hostname `srv1592287` |
| IPv4 | `147.93.103.147` |
| IPv6 | `2a02:4780:12:bec1::1` |
| SSH | `ssh -i ~/.ssh/hostinger_hrms root@147.93.103.147` (key lives on the owner's computer; the owner's computer is the machine that deploys) |
| Code dir | `/opt/hrms` (**not a git repository**; files are copied in) |
| Compose file | `/opt/hrms/docker-compose.vps.yml` (project name `hrms-prod`) |
| Web container | `hrms-prod-web-1`, image `hrms-web:latest`, port `127.0.0.1:3001 -> 3000` |
| Other HRMS containers | `hrms-prod-api-1` (8001), `-worker-1`, `-beat-1`, `-postgres-1`, `-redis-1`, `-minio-1` (9100) |
| Public domains | `krewoxa.com` redirects to `www.krewoxa.com`, plus `api.krewoxa.com`, `storage.krewoxa.com` |
| TLS and proxy | Host nginx (`/etc/nginx/sites-enabled/krewoxa`) proxies to the loopback ports above. Let's Encrypt certificates. Nothing to do for a web deploy. |
| Backups dir | `/opt/hrms-backups/` (create sub-folders per deploy; never delete old ones) |
| Env file | `/opt/hrms/.env` holds `NEXT_PUBLIC_API_URL`, `IMAGE_TAG`, domains. Compose reads it on build. Leave it alone. |

The web image is built **on the server** from `/opt/hrms/apps/web` (multi-stage Dockerfile, Next.js `output: "standalone"`). There is no registry and no CI deploy. A change only goes live after the image is rebuilt there.

Important Dockerfile detail: it must contain `COPY --from=builder --chown=node:node /app/public ./public`. Without it every `/brand`, `/mascot` and `/landing` image returns 404 in production. The server copy has it; the deploy script below aborts if it is missing.

## 2. Access note for AI assistants

Claude Code's auto-mode permission check may deny SSH to production on the first attempt. If that happens, do not look for a workaround. Tell the owner what you wanted to do and why, and either let them run the command or have them confirm in chat and add a Bash permission rule. After the owner explicitly confirmed in chat, the read-only check and the deploys ran normally.

## 3. Procedure

### Step A. Make and verify the change locally
- Edit in `apps/web/src/...` or `apps/web/public/...`.
- Run the web dev server (`web` entry in `.claude/launch.json`, port 3000) and look at the page. Check the console and `npx tsc --noEmit` from `apps/web`.
- Work out the **exact list of changed files**. Only those files go to the server. The local working tree usually has unrelated uncommitted changes (settings pages, API, etc.). Never copy those.

### Step B. Pre-flight on the server (read only)
```bash
ssh -i ~/.ssh/hostinger_hrms root@147.93.103.147 '
hostname                                   # must print srv1592287
cd /opt/hrms
grep -c "/app/public ./public" apps/web/Dockerfile        # must print 1
sha256sum <each file you will change>      # compare with the local ORIGINAL (git show origin/main:path | sha256sum)
docker ps --format "{{.Names}} {{.Status}}" | grep hrms-prod
docker ps -a --format "{{.ID}} {{.Names}} {{.Status}}" | grep -i hirico   # record this
ls -la --time-style=full-iso /root/hirico | sha256sum                    # record this
'
```
If the server hashes do not equal the original versions, the server has changes you do not know about. Stop and ask the owner.

### Step C. Back up, copy, rebuild only web
Run as one script so it aborts safely. Replace `FILES` with the changed paths (relative to repo root, all under `apps/web/`).

```bash
# on the owner's computer
TS=$(date +%Y%m%d-%H%M%S)
scp -i ~/.ssh/hostinger_hrms <changed files> root@147.93.103.147:/tmp/      # flat copy into /tmp
ssh -i ~/.ssh/hostinger_hrms root@147.93.103.147 "TS=$TS bash -s" <<'EOF'
set -euo pipefail
cd /opt/hrms
[ "$(hostname)" = srv1592287 ] || { echo "ABORT wrong server"; exit 1; }
grep -q '/app/public ./public' apps/web/Dockerfile || { echo "ABORT Dockerfile lacks public/ copy"; exit 1; }
BK=/opt/hrms-backups/web-$TS
mkdir -p "$BK"
# 1. back up each file that will be overwritten (preserve path)
for f in apps/web/path/one apps/web/path/two; do          # <-- EDIT list
  mkdir -p "$BK/$(dirname $f)"; cp -a "$f" "$BK/$f"
done
# 2. keep the previous image for instant rollback
docker tag hrms-web:latest hrms-web:pre-web-$TS
# 3. place the new files
cp /tmp/one  apps/web/path/one                              # <-- EDIT mapping
cp /tmp/two  apps/web/path/two
# 4. build web only; restore files if the build fails (live site untouched until `up`)
if ! docker compose -f docker-compose.vps.yml build web; then
  for f in apps/web/path/one apps/web/path/two; do cp -a "$BK/$f" "$f"; done
  echo "ABORT build failed, files restored"; exit 1
fi
# 5. swap only the web container
docker compose -f docker-compose.vps.yml up -d --no-deps web
sleep 20
docker ps --format '{{.Names}} {{.Status}}' | grep hrms-prod
echo "backup=$BK  rollback-image=hrms-web:pre-web-$TS"
EOF
```
A patch file works too for text edits: `scp` the patch, `patch -p1 --dry-run`, then `patch -p1` (this is what the hero removal used). Use plain file copies for images and SVGs.

Expected: the build takes under a minute (`Image hrms-web:latest Built`), then `Container hrms-prod-web-1 Recreate/Started`, then `hrms-prod-web-1 Up 20 seconds (healthy)`. All other containers keep their old uptimes.

### Step D. Verify
```bash
# Hirico untouched: must equal the Step B record (same IDs, still "Up 2 weeks"-style uptime, same hash)
ssh ... 'docker ps -a --format "{{.ID}} {{.Names}} {{.Status}}" | grep -i hirico; ls -la --time-style=full-iso /root/hirico | sha256sum'
# Public site
curl -sSL -o /dev/null -w "home %{http_code}\n" https://www.krewoxa.com/          # 200 (krewoxa.com 301s to www)
curl -sS  -o /dev/null -w "logo %{http_code}\n" https://www.krewoxa.com/brand/krewoxa-logo.svg   # 200
curl -sSL https://www.krewoxa.com/ | grep -c "<text you added or removed>"
```
Check the changed thing itself (an HTML marker, an SVG string, a CSS class), not just a 200. If a browser is available, hard refresh to avoid cache.

### Step E. Report to the owner
List: files changed, container restarted (web only), health, Hirico before/after identical, backup folder and rollback image names, leftover temp files in `/tmp` (leave them, nothing is deleted), and that the change is **not yet committed to git**.

## 4. Rollback (web only)

Instant (previous image, no rebuild):
```bash
ssh -i ~/.ssh/hostinger_hrms root@147.93.103.147 '
cd /opt/hrms
docker tag hrms-web:pre-web-<TS> hrms-web:latest
docker compose -f docker-compose.vps.yml up -d --no-deps web'
```
Source files can also be copied back from `/opt/hrms-backups/web-<TS>/`. Existing rollback images: `hrms-web:pre-landing-edit` (before hero penguin removal), `hrms-web:pre-penguin-k-20261104-161131` (before the ID-card K fix). Backup of the original penguin SVGs: `/opt/hrms-backups/mascot-20261104-161131/`.

## 5. Gotchas and history

- **The server is not git.** A later deploy from `main` or a full copy of the repo will overwrite server files. Before any broad sync, commit the live changes (below) or the old versions come back.
- **Uncommitted at time of writing:** the hero penguin removal in `apps/web/src/components/landing/landing.tsx` and `landing.css`, and the seven mascot SVGs with the new logo K. They are live but only exist in the owner's working tree until committed.
- **Don't copy unrelated local work.** At the time, the local tree also had edits to settings pages, API router, `nav-items.ts`, the Dockerfile and more. None of that was deployed.
- **Dev compose is forbidden** on the server (`docker-compose.yml`). Always `-f docker-compose.vps.yml`. `docker-compose.prod.yml` is for a host without its own nginx and is not used here.
- **Build needs ~2 GB free RAM and disk** (server had 77 GB free). Only `web` is built; do not build `api`.
- **Brief downtime:** the web container is recreated, so the site is unavailable for a few seconds. The API stays up.
- **Landing page sources:** `apps/web/src/components/landing/{landing.tsx,hero-dashboard.tsx,tilt.tsx,landing.css}`, route `apps/web/src/app/page.tsx`, images in `apps/web/public/{brand,landing,mascot}`. A single-file copy of all of it for design handoff is `landing-page-code.md` at the repo root (regenerate after changes).
- **Mascot K on the ID card** is the real logo mark (same clip paths and gradients as `public/brand/krewoxa-logo.svg`), inlined with ids prefixed `bkx...`. `penguin-welcome.svg` holds a text sign (no K) and `penguin-holding-hands.svg` has no card.

## 6. Change log

| Date (UTC) | Change | Files | Rollback image |
|---|---|---|---|
| 2026-11-04 | Removed the penguin that held the hero dashboard | `landing.tsx`, `landing.css` | `hrms-web:pre-landing-edit` |
| 2026-11-04 | ID-card K on seven penguins now matches the logo | `public/mascot/penguin-{celebrating,clipboard,explaining,holding,standing,thinking,waving}.svg` | `hrms-web:pre-penguin-k-20261104-161131` |
