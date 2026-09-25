/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // RELEASE_HARDENING_PHASE_3B §2 — a self-contained `.next/standalone` server bundle (only the
  // traced production dependencies, not the full `node_modules`) so the production Docker image
  // can be a slim multi-stage build (apps/web/Dockerfile) instead of shipping the whole workspace.
  output: "standalone",
};

export default nextConfig;
