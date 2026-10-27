"""Provision the open-source face engine's model files (YuNet + SFace) into a directory.

    python scripts/face/fetch_opensource_assets.py models/face/opensource-v1

Run by an operator at build/provisioning time - the API never downloads models. Every file is
checked against the SHA-256 pinned in `hrms.modules.attendance.opensource_face.assets`; a file
that differs is deleted and the script exits non-zero. Read the licence / provenance notes in
docs/operations/OPEN_SOURCE_FACE_ATTENDANCE_SETUP.md before enabling the engine."""

import sys
import urllib.request
from pathlib import Path

from hrms.modules.attendance.opensource_face.assets import ASSETS, sha256_file


def main(target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    for name, (expected, url, licence) in ASSETS.items():
        dest = target / name
        if dest.is_file() and sha256_file(dest) == expected:
            print(f"ok      {name} ({licence}, already present)")
            continue
        partial = dest.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:  # noqa: S310
            while chunk := response.read(1 << 20):
                out.write(chunk)
        if sha256_file(partial) != expected:
            partial.unlink()
            print(f"FAILED  {name}: checksum mismatch (file discarded)")
            return 1
        partial.replace(dest)
        print(f"fetched {name} ({licence})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "models/face/opensource-v1")))
