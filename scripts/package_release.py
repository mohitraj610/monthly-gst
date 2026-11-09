"""Package committed source and prebuilt assets for the Windows release."""

import hashlib
import io
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_JS = ("react", "react-dom", "scheduler", "lucide-react")


def main():
    frontend = ROOT / "frontend"
    version = json.loads((frontend / "package.json").read_text(encoding="utf-8"))["version"]
    dist = frontend / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("Build the frontend before packaging the release")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT).returncode:
        raise SystemExit("Commit the reviewed source before packaging the release")

    source = subprocess.check_output(["git", "archive", "--format=zip", "HEAD"], cwd=ROOT)
    with ZipFile(io.BytesIO(source)) as archive:
        files = {entry.filename: archive.read(entry) for entry in archive.infolist() if not entry.is_dir()}
    for path in dist.rglob("*"):
        if path.is_file():
            if path.suffix not in {".html", ".js", ".css"}:
                raise SystemExit(f"Unexpected build artifact: {path.name}")
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()

    notices = []
    for name in RUNTIME_JS:
        package = frontend / "node_modules" / name
        meta = json.loads((package / "package.json").read_text(encoding="utf-8"))
        licenses = sorted(path for path in package.glob("LICENSE*") if path.is_file())
        if not licenses:
            raise SystemExit(f"License missing for {name}")
        notices.append(f"{name} {meta['version']}\n\n" + "\n\n".join(path.read_text(encoding="utf-8") for path in licenses))
    files["THIRD-PARTY-NOTICES.txt"] = "\n\n".join(notices).encode()

    prefix = f"monthly-gst-{version}"
    output = ROOT / ".local" / "releases" / f"{prefix}-windows.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w") as archive:
        for name, data in sorted(files.items()):
            entry = ZipInfo(f"{prefix}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, data)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{checksum}  {output.name}\n", encoding="ascii")
    print(f"{output}\nSHA-256 {checksum}")


if __name__ == "__main__":
    main()
