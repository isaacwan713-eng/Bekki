"""Create a privacy-conscious Bekki/FM debugging bundle.

Place this file in the Bekki project root and run:
    python collect_bekki_fm_debug.py

The ZIP is created beside this script. Original project files are never changed.
"""

from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT = ROOT / f"Bekki_FM_debug_bundle_{STAMP}.zip"

# Only text/code useful for diagnosing the AI-controlled FM workflow is included.
ALLOWED_SUFFIXES = {
    ".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".spec", ".log",
}

EXCLUDED_DIRS = {
    ".git", ".idea", ".vscode", ".venv", "venv", "env",
    "__pycache__", "build", "dist", "node_modules", "models",
    "downloads", "screenshots", "images", "cache", ".cache",
}

# Runtime/user data can contain memories, cookies, downloads, or personal paths.
EXCLUDED_TOP_LEVEL_DIRS = {"data", "memory", "cookies", "profiles", "user_data"}
EXCLUDED_NAMES = {
    ".env", ".env.local", ".env.production", "secrets.json",
    "credentials.json", "token.json", "cookies.json",
}

# Replace common inline secret assignments in the copy written to the ZIP.
SECRET_ASSIGNMENT = re.compile(
    r"(?im)^(\s*[A-Za-z_][A-Za-z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASSWD|COOKIE)"
    r"[A-Za-z0-9_]*\s*[:=]\s*)([^\r\n#]+)"
)
BEARER_TOKEN = re.compile(r"(?i)(Authorization\s*[:=]\s*Bearer\s+)[^\s\"']+")


def excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if path.name.lower() in EXCLUDED_NAMES:
        return True
    parts_lower = [part.lower() for part in rel.parts]
    if any(part in EXCLUDED_DIRS for part in parts_lower[:-1]):
        return True
    if parts_lower and parts_lower[0] in EXCLUDED_TOP_LEVEL_DIRS:
        return True
    if path == OUTPUT or path.suffix.lower() == ".zip":
        return True
    return False


def sanitize(text: str) -> str:
    text = SECRET_ASSIGNMENT.sub(r"\1'REDACTED'", text)
    return BEARER_TOKEN.sub(r"\1REDACTED", text)


def candidate_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or excluded(path):
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        # Avoid unexpectedly huge logs/dumps.
        if path.stat().st_size > 10 * 1024 * 1024:
            continue
        files.append(path)
    return sorted(files, key=lambda p: str(p.relative_to(ROOT)).lower())


def main() -> None:
    files = candidate_files()
    manifest_lines = [
        "Bekki FM debug bundle",
        f"Created: {datetime.now().isoformat(timespec='seconds')}",
        f"Project root: {ROOT}",
        "",
        "Included files:",
    ]

    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            relative = path.relative_to(ROOT)
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="replace")
            zf.writestr(relative.as_posix(), sanitize(text))
            manifest_lines.append(f"- {relative.as_posix()}")

        zf.writestr("_BUNDLE_MANIFEST.txt", "\n".join(manifest_lines) + "\n")

    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print("\nFinished.")
    print(f"ZIP: {OUTPUT}")
    print(f"Files: {len(files)}")
    print(f"Size: {size_mb:.2f} MB")
    print("\nUpload this ZIP in ChatGPT.")
    print("Important: terminal output is included only if it was already saved as a .log or .txt file.")


if __name__ == "__main__":
    main()
