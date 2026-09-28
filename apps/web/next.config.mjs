/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // RELEASE_HARDENING_PHASE_3B §2 — a self-contained `.next/standalone` server bundle (only the
  // traced production dependencies, not the full `node_modules`) so the production Docker image
  // can be a slim multi-stage build (apps/web/Dockerfile) instead of shipping the whole workspace.
  output: "standalone",
  eslint: {
    // DevOps Phase A — `.eslintrc.json` (new) is the first ESLint config this app has ever had;
    // without this flag, `next build` folds ESLint into the build step and the pre-existing,
    // as-yet-untriaged lint backlog (7 violations across 6 files, none touched by Phase A) would
    // turn "the production build broke" into the wrong story for a lint finding. CI runs ESLint
    // as its own separate, explicitly non-blocking step instead — see docs/devops/CI.md.
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
