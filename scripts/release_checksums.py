"""Create a SHA256 file for the actual release archive."""
import hashlib
import sys
from pathlib import Path

asset = sys.argv[1]
paths = [Path(asset + ext) for ext in (".tar.gz", ".zip", ".dmg") if Path(asset + ext).is_file()]
if len(paths) != 1:
    raise SystemExit(f"Expected exactly one archive for {asset}: {paths}")
archive = paths[0]
with archive.open("rb") as source:
    digest = hashlib.file_digest(source, "sha256").hexdigest()
Path(asset + ".sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
print(f"{archive.name}: {digest}")
