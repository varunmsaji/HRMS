/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // RELEASE_HARDENING_PHASE_3B §2 — a self-contained `.next/standalone` server bundle (only the
  // traced production dependencies, not the full `node_modules`) so the production Docker image
  // can be a slim multi-stage build (apps/web/Dockerfile) instead of shipping the whole workspace.
  output: "standalone",
  // FINDING-02 (Next 16 upgrade) — `next build` no longer folds ESLint into the build step at
  // all (the `eslint` config key itself was removed, not just this flag), so the DevOps Phase A
  // `ignoreDuringBuilds` escape hatch that used to live here is now a no-op Next warns about on
  // every build. CI's separate, explicitly non-blocking ESLint step (docs/devops/CI.md) is
  // unaffected — it never went through this key.
};

export default nextConfig;
