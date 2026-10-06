import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

// FINDING-02 (Next 16 upgrade) — replaces `.eslintrc.json`'s `extends: "next/core-web-vitals"`.
// `next lint` itself was removed in Next 16; `eslint-config-next@16` only ships a flat config,
// consumed directly by the `eslint` CLI (package.json's `lint` script, CI's ESLint step).
export default defineConfig([
  ...nextVitals,
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
