#!/usr/bin/env python3
"""Build slim Linux-compatible Lambda deployment zips for Creative Agent."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = PROJECT_ROOT / "infra" / "terraform" / "build"

# Back-compat: terraform still references build/lambda.zip (composer package).
DEFAULT_OUTPUT = BUILD_DIR / "lambda.zip"

LAMBDA_PLATFORM = "manylinux2014_x86_64"
LAMBDA_PYTHON = "3.12"

# Bundled at zip root as guide/Agent2-guide.md (Agent 2 system prompt).
GUIDE_FILES = ("Agent2-guide.md",)

# boto3/botocore ship with the Lambda Python runtime — bundling them wastes ~20MB+.
SKIP_PIP_PACKAGES = frozenset({"boto3", "botocore", "s3transfer", "jmespath"})

# Migrations are not run inside Lambda handlers.
SKIP_RUNTIME_PACKAGES = frozenset({"alembic", "mako"})

_BASE_REQUIREMENTS = (
    "pydantic>=2.0",
    # 2.1+ defaults postgresql:// to psycopg (v3); we ship psycopg2-binary.
    "sqlalchemy>=2.0,<2.1",
    "psycopg2-binary>=2.9",
)

# openai 2.x+/3.x add optional httpx2 support; with pruned or incomplete metadata
# Lambda raises PackageNotFoundError: No package metadata was found for httpx2.
# Stay on 1.x until we intentionally adopt httpx2 (and ship its dist-info).
_OPENAI = "openai>=1.40,<2"
_HTTPX = "httpx>=0.27,<0.28"
# starlette 1.6+ prefers httpx2 in TestClient; keep FastAPI on a quieter stack.
_API_REQUIREMENTS = (
    "fastapi>=0.115,<0.128",
    "mangum>=0.19",
    _HTTPX,
    _OPENAI,
    *_BASE_REQUIREMENTS,
)
_COMPOSER_REQUIREMENTS = (_OPENAI, *_BASE_REQUIREMENTS)
_ENHANCER_REQUIREMENTS = (_OPENAI, *_BASE_REQUIREMENTS)
_TTS_REQUIREMENTS = (_OPENAI, _HTTPX, *_BASE_REQUIREMENTS)


@dataclass(frozen=True, slots=True)
class LambdaTarget:
    name: str
    packages: tuple[str, ...]
    requirements: tuple[str, ...]
    include_guide: bool
    default_output: Path
    include_ffmpeg: bool = False


TARGETS: dict[str, LambdaTarget] = {
    "composer": LambdaTarget(
        name="composer",
        packages=("transcript_composer", "db", "queues", "models", "observability"),
        requirements=_COMPOSER_REQUIREMENTS,
        include_guide=False,
        default_output=BUILD_DIR / "lambda-composer.zip",
    ),
    "enhancer": LambdaTarget(
        name="enhancer",
        packages=(
            "tts_enhancer",
            "transcript_composer",  # duration + llm_config imports
            "db",
            "queues",
            "models",
            "observability",
        ),
        requirements=_ENHANCER_REQUIREMENTS,
        include_guide=True,
        default_output=BUILD_DIR / "lambda-enhancer.zip",
    ),
    "api": LambdaTarget(
        name="api",
        packages=(
            "api",
            "transcript_composer",
            "tts_pipeline",
            "db",
            "queues",
            "models",
            "observability",
        ),
        requirements=_API_REQUIREMENTS,
        include_guide=False,
        default_output=BUILD_DIR / "lambda-api.zip",
    ),
    "tts": LambdaTarget(
        name="tts",
        packages=(
            "tts_pipeline",
            "transcript_composer",
            "db",
            "queues",
            "models",
            "observability",
        ),
        requirements=_TTS_REQUIREMENTS,
        include_guide=False,
        include_ffmpeg=True,
        default_output=BUILD_DIR / "lambda-tts.zip",
    ),
    "deps-layer": LambdaTarget(
        name="deps-layer",
        packages=(),
        requirements=_API_REQUIREMENTS,
        include_guide=False,
        default_output=BUILD_DIR / "lambda-deps-layer.zip",
    ),
}


def _run_pip_install(target_dir: Path, requirements: tuple[str, ...]) -> None:
    if not requirements:
        return
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        *requirements,
        "--target",
        str(target_dir),
        "--platform",
        LAMBDA_PLATFORM,
        "--python-version",
        LAMBDA_PYTHON,
        "--implementation",
        "cp",
        "--only-binary",
        ":all:",
        "--upgrade",
        "--no-cache-dir",
    ]
    print(f"Installing {len(requirements)} dependencies for Lambda (linux x86_64)...")
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)


def _prune_staging_dir(staging_dir: Path) -> None:
    """Drop packages and metadata not needed at Lambda runtime."""
    for package_name in SKIP_PIP_PACKAGES | SKIP_RUNTIME_PACKAGES:
        target = staging_dir / package_name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            print(f"Pruned {package_name}/")

    for pattern in ("**/__pycache__", "**/*.pyc", "**/*.pyo", "**/tests", "**/test"):
        for path in staging_dir.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink(missing_ok=True)

    # Keep *.dist-info — importlib.metadata lookups (openai/httpx/tqdm/etc.) need it.
    # Only drop bulky RECORD-adjacent caches if present.
    for extra in ("*.egg-info",):
        for path in staging_dir.glob(extra):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)


def _copy_app_packages(staging_dir: Path, packages: tuple[str, ...]) -> None:
    for package in packages:
        source = PROJECT_ROOT / package
        if not source.is_dir():
            raise FileNotFoundError(f"Expected package directory: {source}")
        destination = staging_dir / package
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
        print(f"Copied {package}/")


def _copy_guide_assets(staging_dir: Path) -> None:
    guide_dest = staging_dir / "guide"
    guide_dest.mkdir(parents=True, exist_ok=True)
    for name in GUIDE_FILES:
        source = PROJECT_ROOT / "guide" / name
        if not source.is_file():
            raise FileNotFoundError(f"Expected guide file: {source}")
        shutil.copy2(source, guide_dest / name)
        print(f"Copied guide/{name}")


def _bundle_ffmpeg_binary(staging_dir: Path) -> None:
    """Include a Linux x86_64 static ffmpeg binary for Lambda final merge/mix.

    Do not bundle ffprobe here: it pushes ``lambda-tts.zip`` over the ~70MB
    direct ``UpdateFunctionCode`` limit. MixBackground resolves duration via
    ``ffmpeg -i`` (and a size estimate fallback) so ``-t`` is always set.
    """
    bin_dir = staging_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_path = bin_dir / "ffmpeg"
    if ffmpeg_path.exists():
        print("ffmpeg binary already present in staging dir")
        return

    import tarfile

    cache_dir = BUILD_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cache_dir / "ffmpeg-release-amd64-static.tar.xz"
    archive_url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"

    if not archive_path.exists() or archive_path.stat().st_size < 40_000_000:
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        print(f"Downloading ffmpeg static build from {archive_url} ...")
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                import httpx

                with httpx.stream("GET", archive_url, follow_redirects=True, timeout=600.0) as response:
                    response.raise_for_status()
                    with archive_path.open("wb") as handle:
                        for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                            handle.write(chunk)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                archive_path.unlink(missing_ok=True)
                print(f"ffmpeg download attempt {attempt} failed: {exc}")
        if last_error is not None:
            raise RuntimeError(f"Could not download ffmpeg static build: {last_error}") from last_error
    else:
        print(f"Using cached ffmpeg archive at {archive_path}")

    with tarfile.open(archive_path, mode="r:xz") as archive:
        member = next(
            (item for item in archive.getmembers() if item.name.endswith("/ffmpeg") and item.isfile()),
            None,
        )
        if member is None:
            raise RuntimeError("Could not locate ffmpeg binary in downloaded archive")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RuntimeError("Failed to extract ffmpeg binary from archive")
        ffmpeg_path.write_bytes(extracted.read())

    ffmpeg_path.chmod(0o755)
    print(f"Bundled ffmpeg at bin/ffmpeg ({ffmpeg_path.stat().st_size // (1024 * 1024)} MB)")


def _zip_directory(source_dir: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Wrote {output_path} ({size_mb:.1f} MB)")


def build_lambda_package(
    *,
    target: LambdaTarget,
    output_path: Path,
    code_only: bool = False,
) -> Path:
    staging_dir = output_path.parent / f"package-{target.name}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    if not code_only:
        _run_pip_install(staging_dir, target.requirements)
        _prune_staging_dir(staging_dir)
    _copy_app_packages(staging_dir, target.packages)
    if target.include_guide:
        _copy_guide_assets(staging_dir)
    if target.include_ffmpeg:
        _bundle_ffmpeg_binary(staging_dir)
    _zip_directory(staging_dir, output_path)
    shutil.rmtree(staging_dir)
    return output_path


def build_code_only_package(*, target_name: str, output_path: Path | None = None) -> Path:
    target = TARGETS[target_name]
    out = output_path or BUILD_DIR / f"lambda-{target_name}-code.zip"
    return build_lambda_package(target=target, output_path=out, code_only=True)


def build_all_targets() -> list[Path]:
    outputs: list[Path] = []
    for name in ("composer", "enhancer", "api", "tts"):
        target = TARGETS[name]
        outputs.append(build_lambda_package(target=target, output_path=target.default_output))
    # Terraform compatibility: composer zip is also published as lambda.zip
    composer_zip = TARGETS["composer"].default_output
    legacy_zip = DEFAULT_OUTPUT
    shutil.copy2(composer_zip, legacy_zip)
    print(f"Copied {composer_zip.name} -> {legacy_zip.name} (terraform default)")
    return outputs + [legacy_zip]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Creative Agent Lambda zip(s)")
    parser.add_argument(
        "--target",
        choices=[*TARGETS.keys(), "all"],
        default="all",
        help="Lambda package to build (default: all)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output zip path (single-target builds only)",
    )
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="App source only (no pip deps). Attach lambda-deps-layer.zip as a Lambda layer.",
    )
    args = parser.parse_args()

    if args.target == "all":
        build_all_targets()
        if args.code_only:
            for name in ("composer", "enhancer", "api", "tts"):
                build_code_only_package(target_name=name)
        return

    target = TARGETS[args.target]
    output_path = (args.output or target.default_output).resolve()
    build_lambda_package(target=target, output_path=output_path, code_only=args.code_only)


if __name__ == "__main__":
    main()
