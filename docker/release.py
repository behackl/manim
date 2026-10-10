"""Publish tested Docker images; releases reuse the main commit's image."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import tomllib
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

IMAGE = "manimcommunity/manim"
ARCHITECTURES = {"amd64", "arm64"}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True, timeout=120).strip()


def version() -> str:
    with Path("pyproject.toml").open("rb") as source:
        return tomllib.load(source)["project"]["version"]


def commit() -> str:
    sha = os.environ["GITHUB_SHA"]
    if (
        not re.fullmatch(r"[0-9a-f]{40}", sha)
        or command("git", "rev-parse", "HEAD") != sha
    ):
        raise ValueError("Checkout does not match the event commit")
    return sha


def check_digest(digest: str) -> str:
    if not DIGEST.fullmatch(digest):
        raise ValueError(f"Invalid image digest: {digest!r}")
    return digest


def inspect(reference: str, field: str) -> dict:
    return json.loads(
        command(
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            reference,
            "--format",
            "{{json ." + field + "}}",
        )
    )


def registry_digest(tag: str) -> str | None:
    """Only 404 means absent; authentication/network errors must not allow a write."""
    query = urlencode(
        {"service": "registry.docker.io", "scope": f"repository:{IMAGE}:pull"}
    )
    with urlopen(f"https://auth.docker.io/token?{query}", timeout=30) as response:
        token = json.load(response)["token"]
    request = Request(
        f"https://registry-1.docker.io/v2/{IMAGE}/manifests/{quote(tag, safe='')}",
        method="HEAD",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": ", ".join(
                [
                    "application/vnd.oci.image.index.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.v2+json",
                ]
            ),
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return check_digest(response.headers["Docker-Content-Digest"])
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def verify(
    digest: str, sha: str, project_version: str, expected: dict | None = None
) -> None:
    """Check both platforms and source/version labels using the immutable digest."""
    reference = f"{IMAGE}@{check_digest(digest)}"
    manifest = inspect(reference, "Manifest")
    entries = manifest.get("manifests", [])
    platforms = {(e["platform"]["os"], e["platform"]["architecture"]) for e in entries}
    if (
        manifest["digest"] != digest
        or len(entries) != 2
        or platforms != {("linux", a) for a in ARCHITECTURES}
    ):
        raise ValueError("Expected exactly linux/amd64 and linux/arm64")
    actual = {e["platform"]["architecture"]: check_digest(e["digest"]) for e in entries}
    if expected is not None and actual != expected:
        raise ValueError("Manifest differs from the tested architecture digests")
    images = inspect(reference, "Image")
    for architecture in ARCHITECTURES:
        platform = f"linux/{architecture}"
        image = images.get(platform) or images.get(f"{platform}/v8")
        if (
            not image
            or image.get("architecture") != architecture
            or image.get("os") != "linux"
        ):
            raise ValueError(f"Wrong {architecture} image configuration")
        labels = image.get("config", {}).get("Labels", {})
        if (
            labels.get("org.opencontainers.image.revision") != sha
            or labels.get("org.opencontainers.image.version") != project_version
        ):
            raise ValueError(f"Wrong source/version in {architecture} image")


def promote(digest: str, tag: str) -> None:
    command(
        "docker",
        "buildx",
        "imagetools",
        "create",
        "--prefer-index=false",
        "--tag",
        f"{IMAGE}:{tag}",
        f"{IMAGE}@{check_digest(digest)}",
    )
    if registry_digest(tag) != digest:
        raise RuntimeError(f"Promotion to {tag} changed the tested digest")


def publish_main(digests: Path) -> None:
    sha, project_version = commit(), version()
    tag = f"sha-{sha}"
    digest = registry_digest(tag)
    if digest is None:
        tested = {}
        for architecture in ARCHITECTURES:
            reference = (digests / f"{architecture}.txt").read_text().strip()
            prefix = f"{IMAGE}@"
            if not reference.startswith(prefix):
                raise ValueError("Unexpected image repository in architecture digest")
            tested[architecture] = check_digest(reference[len(prefix) :])
        temporary = f"{IMAGE}:build-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
        command(
            "docker",
            "buildx",
            "imagetools",
            "create",
            "--tag",
            temporary,
            *(f"{IMAGE}@{tested[a]}" for a in sorted(ARCHITECTURES)),
        )
        digest = check_digest(inspect(temporary, "Manifest")["digest"])
        verify(digest, sha, project_version, tested)
        promote(digest, tag)
    else:
        # First successful build wins. Rerunning the same commit must not change
        # the candidate a release uses, even if system package inputs changed.
        verify(digest, sha, project_version)
    head = json.loads(
        command("gh", "api", "repos/ManimCommunity/manim/git/ref/heads/main")
    )
    if head["object"]["sha"] == sha:
        promote(digest, "latest")
    else:
        print("Main has advanced; keeping its newer latest image.")


def publish_release(tag: str, wait_seconds: int = 1800) -> None:
    sha, project_version = commit(), version()
    if tag != f"v{project_version}":
        raise ValueError("Release tag does not match pyproject.toml")
    digest = registry_digest(tag)
    if digest is None:
        deadline = time.monotonic() + wait_seconds
        while (digest := registry_digest(f"sha-{sha}")) is None:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "No tested image for the release commit. Wait for its main Docker "
                    "build to succeed, then rerun publication. No image was rebuilt."
                )
            time.sleep(15)
        verify(digest, sha, project_version)
        promote(digest, tag)
    else:
        # An existing version is never replaced. Also supports reruns after a
        # successful version publication followed by a failed stable update.
        verify(digest, sha, project_version)
    latest = json.loads(
        command("gh", "api", "repos/ManimCommunity/manim/releases/latest")
    )
    if str(latest["id"]) == os.environ["RELEASE_ID"]:
        promote(digest, "stable")
    else:
        print("A newer release exists; keeping its stable image.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("version")
    publish = commands.add_parser("main")
    publish.add_argument("--digests", type=Path, required=True)
    release = commands.add_parser("release")
    release.add_argument("--tag", required=True)
    release.add_argument("--wait-seconds", type=int, default=1800)
    args = parser.parse_args()
    if args.operation == "version":
        print(f"version={version()}")
    elif args.operation == "main":
        publish_main(args.digests)
    else:
        publish_release(args.tag, args.wait_seconds)


if __name__ == "__main__":
    main()
