#!/usr/bin/env bash
# Convenience entrypoint at the repo root — runs backend + frontend together.
# Usage: ./dev.sh   (equivalent to `npm run dev` / `bash scripts/dev.sh`)
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/dev.sh"
