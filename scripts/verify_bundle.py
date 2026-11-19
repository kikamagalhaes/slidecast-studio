"""Run the packaged app with no developer media tools on PATH; emit JSON evidence."""
import argparse
import json
import os
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("executable")
parser.add_argument("--report", default="bundle-self-test.json")
args = parser.parse_args()
env = os.environ.copy()
for key in ("FFMPEG_PATH", "FFPROBE_PATH", "IMAGEIO_FFMPEG_EXE", "PYTHONPATH", "PYTHONHOME"):
    env.pop(key, None)
env["PATH"] = str(Path(env.get("SystemRoot", "C:/Windows")) / "System32") if os.name == "nt" else ""
env["QT_QPA_PLATFORM"] = "offscreen"
env["SLIDECAST_REQUIRE_BUNDLED_MEDIA"] = "1"
report = Path(args.report).resolve()
result = subprocess.run([str(Path(args.executable).resolve()), "--self-test", "--self-test-report", str(report)], env=env, timeout=180)
if result.returncode:
    raise SystemExit(result.returncode)
proof = json.loads(report.read_text(encoding="utf-8"))
assert not proof["failures"], proof
assert set(proof["media_tools"]) == {"ffmpeg", "ffprobe"}, proof
assert set(proof["renders"]) == {"pdf", "mp4"}, proof
assert proof["themes"] == ["light", "dark"], proof
assert proof["capture_inputs"], proof
print(json.dumps(proof, ensure_ascii=False, indent=2))
