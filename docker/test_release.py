"""Offline tests for Docker publication; no container or registry is contacted."""

# ruff: noqa: PT009, PT027

from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch
from urllib.error import HTTPError

import release

SHA = "a" * 40
DIGEST = "sha256:" + "1" * 64
ARCHES = {"amd64": "sha256:" + "2" * 64, "arm64": "sha256:" + "3" * 64}
VERSION = "1.2.3"


def manifest():
    return {
        "digest": DIGEST,
        "manifests": [
            {"digest": digest, "platform": {"os": "linux", "architecture": arch}}
            for arch, digest in ARCHES.items()
        ],
    }


def images():
    return {
        f"linux/{arch}": {
            "architecture": arch,
            "os": "linux",
            "config": {
                "Labels": {
                    "org.opencontainers.image.revision": SHA,
                    "org.opencontainers.image.version": VERSION,
                }
            },
        }
        for arch in ARCHES
    }


class PublicationTests(unittest.TestCase):
    def setUp(self):
        environment = {
            "GITHUB_SHA": SHA,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "RELEASE_ID": "42",
        }
        self.environment = patch.dict(os.environ, environment)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.real_commit, self.real_verify = release.commit, release.verify
        for name, value in {"commit": SHA, "version": VERSION}.items():
            patcher = patch.object(release, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        verifier = patch.object(release, "verify")
        self.verify = verifier.start()
        self.addCleanup(verifier.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)
        for arch, digest in ARCHES.items():
            (self.path / f"{arch}.txt").write_text(f"{release.IMAGE}@{digest}")

    def test_verify_platforms_labels_and_tested_digests(self):
        configs = images()
        configs["linux/arm64/v8"] = configs.pop("linux/arm64")
        with patch.object(release, "inspect", side_effect=[manifest(), configs]):
            self.real_verify(DIGEST, SHA, VERSION, ARCHES)

    def test_verify_rejects_partial_duplicate_wrong_platform_or_digest(self):
        original = manifest()
        partial = copy.deepcopy(original)
        partial["manifests"].pop()
        duplicate = copy.deepcopy(original)
        duplicate["manifests"][1] = duplicate["manifests"][0]
        wrong_os = copy.deepcopy(original)
        wrong_os["manifests"][0]["platform"]["os"] = "windows"
        wrong_digest = copy.deepcopy(original)
        wrong_digest["digest"] = ARCHES["amd64"]
        for candidate in (partial, duplicate, wrong_os, wrong_digest):
            with (
                self.subTest(candidate=candidate),
                patch.object(release, "inspect", return_value=candidate),
                self.assertRaises(ValueError),
            ):
                self.real_verify(DIGEST, SHA, VERSION)

    def test_verify_rejects_wrong_source_version_or_architecture(self):
        for label, value in [
            ("org.opencontainers.image.revision", "b" * 40),
            ("org.opencontainers.image.version", "9.9.9"),
        ]:
            configs = images()
            configs["linux/amd64"]["config"]["Labels"][label] = value
            with (
                self.subTest(label=label),
                patch.object(release, "inspect", side_effect=[manifest(), configs]),
                self.assertRaises(ValueError),
            ):
                self.real_verify(DIGEST, SHA, VERSION)
        configs = images()
        configs["linux/arm64"]["architecture"] = "amd64"
        with (
            patch.object(release, "inspect", side_effect=[manifest(), configs]),
            self.assertRaises(ValueError),
        ):
            self.real_verify(DIGEST, SHA, VERSION)

    def test_verify_rejects_untested_architecture_digest(self):
        with (
            patch.object(release, "inspect", return_value=manifest()),
            self.assertRaises(ValueError),
        ):
            self.real_verify(DIGEST, SHA, VERSION, {**ARCHES, "arm64": DIGEST})

    def test_promotion_preserves_digest(self):
        with (
            patch.object(release, "command") as command,
            patch.object(release, "registry_digest", return_value=DIGEST),
        ):
            release.promote(DIGEST, "stable")
        command.assert_called_once_with(
            "docker",
            "buildx",
            "imagetools",
            "create",
            "--prefer-index=false",
            "--tag",
            f"{release.IMAGE}:stable",
            f"{release.IMAGE}@{DIGEST}",
        )

    def test_promotion_rejects_changed_digest(self):
        with (
            patch.object(release, "command"),
            patch.object(release, "registry_digest", return_value=ARCHES["amd64"]),
            self.assertRaises(RuntimeError),
        ):
            release.promote(DIGEST, "stable")

    def test_main_records_only_the_verified_digest_then_updates_latest(self):
        ordering = Mock()
        ordering.attach_mock(self.verify, "verify")
        with (
            patch.object(release, "registry_digest", return_value=None),
            patch.object(release, "inspect", return_value=manifest()),
            patch.object(
                release, "command", return_value=json.dumps({"object": {"sha": SHA}})
            ),
            patch.object(release, "promote") as promote,
        ):
            ordering.attach_mock(promote, "promote")
            release.publish_main(self.path)
        self.assertEqual(
            ordering.mock_calls,
            [
                call.verify(DIGEST, SHA, VERSION, ARCHES),
                call.promote(DIGEST, f"sha-{SHA}"),
                call.promote(DIGEST, "latest"),
            ],
        )

    def test_main_rerun_reuses_first_candidate(self):
        with (
            patch.object(release, "registry_digest", return_value=DIGEST),
            patch.object(
                release, "command", return_value=json.dumps({"object": {"sha": SHA}})
            ) as command,
            patch.object(release, "promote") as promote,
        ):
            release.publish_main(self.path)
        self.verify.assert_called_once_with(DIGEST, SHA, VERSION)
        promote.assert_called_once_with(DIGEST, "latest")
        self.assertEqual(command.call_count, 1)  # Only the main-head API query.

    def test_old_main_does_not_overwrite_latest(self):
        with (
            patch.object(release, "registry_digest", return_value=DIGEST),
            patch.object(
                release,
                "command",
                return_value=json.dumps({"object": {"sha": "b" * 40}}),
            ),
            patch.object(release, "promote") as promote,
        ):
            release.publish_main(self.path)
        promote.assert_not_called()

    def test_main_rejects_another_repository_in_digest_file(self):
        (self.path / "amd64.txt").write_text(f"someone/image@{DIGEST}")
        with (
            patch.object(release, "registry_digest", return_value=None),
            patch.object(release, "promote") as promote,
            self.assertRaises(ValueError),
        ):
            release.publish_main(self.path)
        promote.assert_not_called()

    def test_release_uses_commit_digest_without_rebuilding(self):
        with (
            patch.object(release, "registry_digest", side_effect=[None, DIGEST]),
            patch.object(release, "command", return_value='{"id": 42}'),
            patch.object(release, "promote") as promote,
        ):
            release.publish_release("v1.2.3")
        self.verify.assert_called_once_with(DIGEST, SHA, VERSION)
        self.assertEqual(
            promote.call_args_list, [call(DIGEST, "v1.2.3"), call(DIGEST, "stable")]
        )

    def test_release_rerun_reuses_existing_version_without_replacing_it(self):
        with (
            patch.object(release, "registry_digest", return_value=DIGEST) as registry,
            patch.object(release, "command", return_value='{"id": 42}'),
            patch.object(release, "promote") as promote,
        ):
            release.publish_release("v1.2.3")
        registry.assert_called_once_with("v1.2.3")
        self.verify.assert_called_once_with(DIGEST, SHA, VERSION)
        promote.assert_called_once_with(DIGEST, "stable")

    def test_conflicting_existing_version_is_not_overwritten(self):
        self.verify.side_effect = ValueError("Wrong source/version")
        with (
            patch.object(release, "registry_digest", return_value=DIGEST),
            patch.object(release, "promote") as promote,
            self.assertRaises(ValueError),
        ):
            release.publish_release("v1.2.3")
        promote.assert_not_called()

    def test_old_release_does_not_overwrite_stable(self):
        with (
            patch.object(release, "registry_digest", side_effect=[None, DIGEST]),
            patch.object(release, "command", return_value='{"id": 99}'),
            patch.object(release, "promote") as promote,
        ):
            release.publish_release("v1.2.3")
        promote.assert_called_once_with(DIGEST, "v1.2.3")

    def test_missing_candidate_fails_without_rebuilding(self):
        with (
            patch.object(release, "registry_digest", return_value=None),
            patch.object(release, "promote") as promote,
            self.assertRaisesRegex(RuntimeError, "No image was rebuilt"),
        ):
            release.publish_release("v1.2.3", wait_seconds=0)
        promote.assert_not_called()

    def test_release_waits_for_main_candidate(self):
        with (
            patch.object(release, "registry_digest", side_effect=[None, None, DIGEST]),
            patch.object(release.time, "sleep") as sleep,
            patch.object(release, "command", return_value='{"id": 42}'),
            patch.object(release, "promote"),
        ):
            release.publish_release("v1.2.3")
        sleep.assert_called_once_with(15)

    def test_wrong_version_does_not_query_registry(self):
        with (
            patch.object(release, "registry_digest") as registry,
            self.assertRaises(ValueError),
        ):
            release.publish_release("v9.9.9")
        registry.assert_not_called()

    def test_moved_tag_cannot_change_event_commit(self):
        with (
            patch.object(release, "command", return_value="b" * 40),
            self.assertRaisesRegex(ValueError, "event commit"),
        ):
            self.real_commit()

    def test_registry_only_treats_404_as_missing(self):
        for code in (404, 401, 403, 429, 500):
            response = io.BytesIO(b'{"token": "test-token"}')
            error = HTTPError("https://registry.test/", code, "failure", {}, None)
            with (
                self.subTest(code=code),
                patch.object(release, "urlopen", side_effect=[response, error]),
            ):
                if code == 404:
                    self.assertIsNone(release.registry_digest("v1.2.3"))
                else:
                    with self.assertRaises(HTTPError):
                        release.registry_digest("v1.2.3")

    def test_registry_returns_validated_header_digest(self):
        response = nullcontext(
            SimpleNamespace(headers={"Docker-Content-Digest": DIGEST})
        )
        with patch.object(
            release,
            "urlopen",
            side_effect=[io.BytesIO(b'{"token": "test-token"}'), response],
        ):
            self.assertEqual(release.registry_digest("v1.2.3"), DIGEST)


if __name__ == "__main__":
    unittest.main()
