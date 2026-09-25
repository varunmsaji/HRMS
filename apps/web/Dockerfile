# syntax=docker/dockerfile:1

# Dependencies — isolated so `npm ci` is only re-run when the lockfile actually changes.
# `libc6-compat` is required on Alpine (musl, not glibc) for Next.js's prebuilt SWC binary —
# without it, `next build` fails to load `@next/swc-linux-x64-gnu` at all (the documented Next.js
# Docker fix: https://nextjs.org/docs/messages/failed-loading-swc).
FROM node:20-alpine AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Builder — `next build` with `output: "standalone"` (next.config.mjs) traces the minimal
# production dependency set into `.next/standalone`, instead of shipping the full `node_modules`.
FROM node:20-alpine AS builder
RUN apk add --no-cache libc6-compat
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* vars are inlined into the client JS bundle at build time, not read at container
# start — the image must be rebuilt (not just restarted with a new env var) to change this.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Runtime — only the standalone server bundle + static assets; no npm/node_modules build tooling,
# no source, no test files (RELEASE_HARDENING_PHASE_3B §2).
FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# The official node:20-alpine image already ships a non-root `node` user/group at uid/gid 1000 —
# reused here rather than creating a second one (uid 1000 is already taken).
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node

EXPOSE 3000

# Liveness probe against a statically prerendered route (no API/auth dependency of its own) —
# Node's built-in `fetch` (global since Node 18) avoids needing curl/wget in the alpine image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/login').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

# `server.js` (from `.next/standalone`) already handles SIGTERM for graceful shutdown; it is
# PID 1 here (no shell wrapper), so signals reach it directly.
CMD ["node", "server.js"]
