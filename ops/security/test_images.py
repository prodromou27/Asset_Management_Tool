"""Scan the configured runtime build, never a stale upstream image with the same role."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scan import ROOT, image_for


class ImageSelectionTests(unittest.TestCase):
    @patch("scan.run")
    def test_runtime_build_takes_precedence_over_image_tag(self, run):
        context = str(ROOT / "infra/runtime")
        service = {
            "image": "itam-postgres:16.15",
            "build": {"context": context, "target": "postgres"},
        }
        image = image_for(service, "postgres", "123456789012abcdef")
        run.assert_called_once_with(
            ["docker", "build", "--pull=false", "-t", image, "--target", "postgres", context],
            cwd=ROOT,
        )

    @patch("scan.run")
    def test_backup_build_retains_its_dockerfile_and_stage(self, run):
        context = str(ROOT / "backend")
        image_for(
            {"build": {"context": context, "dockerfile": "Dockerfile", "target": "backup-runner"}},
            "backup-worker",
            "123456789012abcdef",
        )
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--target") + 1], "backup-runner")
        self.assertEqual(args[args.index("-f") + 1], str(Path(context) / "Dockerfile"))

    @patch("scan.run")
    def test_external_image_uses_configured_reference(self, run):
        self.assertEqual(
            image_for({"image": "pinned@sha256:example"}, "proxy", "abc"), "pinned@sha256:example"
        )
        run.assert_called_once_with(["docker", "pull", "pinned@sha256:example"])
