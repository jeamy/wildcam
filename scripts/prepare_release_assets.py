#!/usr/bin/env python3
"""Prepare GitHub release assets without exceeding the per-asset size limit."""

from __future__ import annotations

import argparse
import glob
import hashlib
from pathlib import Path
import shutil


DEFAULT_MAX_ASSET_SIZE = 1900 * 1024 * 1024
BUFFER_SIZE = 8 * 1024 * 1024


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(BUFFER_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_file(source: Path, release_dir: Path, max_asset_size: int) -> list[Path]:
    parts: list[Path] = []
    part_number = 1

    with source.open("rb") as handle:
        while True:
            target = release_dir / f"{source.name}.part{part_number:02d}"
            written = 0

            with target.open("wb") as output:
                while written < max_asset_size:
                    chunk = handle.read(min(BUFFER_SIZE, max_asset_size - written))
                    if not chunk:
                        break
                    output.write(chunk)
                    written += len(chunk)

            if written == 0:
                target.unlink(missing_ok=True)
                break

            parts.append(target)
            part_number += 1

    return parts


def find_sources(platform: str, include_appimage: bool) -> list[Path]:
    patterns = [f"dist/*_{platform}_*.zip"]
    if include_appimage:
        patterns.append(f"dist/*_{platform}_*.AppImage")

    return [Path(path) for pattern in patterns for path in glob.glob(pattern)]


def prepare_release_assets(platform: str, include_appimage: bool, max_asset_size: int) -> None:
    release_dir = Path("dist") / "release-assets"
    release_dir.mkdir(parents=True, exist_ok=True)

    sources = find_sources(platform, include_appimage)
    if not sources:
        raise SystemExit("No release assets found")

    checksums: list[str] = []
    split_assets: list[str] = []

    for source in sources:
        if source.stat().st_size < max_asset_size:
            target = release_dir / source.name
            shutil.copy2(source, target)
            checksums.append(f"{file_sha256(target)}  {target.name}")
            continue

        split_assets.append(source.name)
        for part in split_file(source, release_dir, max_asset_size):
            checksums.append(f"{file_sha256(part)}  {part.name}")

    checksum_path = release_dir / f"wildcam_{platform}_SHA256SUMS.txt"
    checksum_path.write_text("\n".join(checksums) + "\n", encoding="utf-8")

    if split_assets:
        note_path = release_dir / f"wildcam_{platform}_split_assets.txt"
        note_path.write_text(
            "Some release assets exceeded GitHub's 2 GiB per-file limit and were split.\n"
            "Reassemble a split asset with: cat <asset>.part* > <asset>\n"
            "Split assets:\n"
            + "\n".join(f"- {asset}" for asset in split_assets)
            + "\n",
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True)
    parser.add_argument("--include-appimage", action="store_true")
    parser.add_argument("--max-asset-size", type=int, default=DEFAULT_MAX_ASSET_SIZE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prepare_release_assets(args.platform, args.include_appimage, args.max_asset_size)


if __name__ == "__main__":
    main()
