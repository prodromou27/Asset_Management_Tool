"""Scan the configured runtime build, never a stale upstream image with the same role."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scan import ROOT, image_for, production_compose, sqlite_proof


class ImageSelectionTests(unittest.TestCase):
    @patch("scan.subprocess.run")
    @patch("scan.run", return_value='{"passed":true}')
    def test_sqlite_probe_has_empty_environment_readonly_networkless_limits(self, run, cleanup):
        self.assertEqual(sqlite_proof("sha256:fixture"), {"passed": True})
        args = run.call_args.args[0]
        for option, value in (("--network", "none"), ("--memory", "256m"), ("--pids-limit", "32")):
            self.assertEqual(args[args.index(option) + 1], value)
        self.assertIn("--read-only", args)
        self.assertEqual(args[args.index("sha256:fixture") + 1], "-i")
        self.assertEqual(run.call_args.kwargs["timeout"], 30)
        self.assertEqual(cleanup.call_args.args[0][-1], args[args.index("--name") + 1])

    @patch("scan.subprocess.run")
    @patch("scan.run", side_effect=TimeoutError("fixture timeout"))
    def test_timed_out_probe_still_cleans_up_only_its_generated_container(self, run, cleanup):
        with self.assertRaises(TimeoutError):
            sqlite_proof("sha256:fixture")
        self.assertTrue(cleanup.call_args.args[0][-1].startswith("itam-sqlite-proof-"))

    @patch("scan.run", return_value='{"services":{"backup-worker":{}}}')
    def test_production_config_enables_optional_backup_service(self, run):
        self.assertIn("backup-worker", production_compose()["services"])
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--profile") + 1], "backups")
        self.assertIn("infra/compose.prod.yaml", args)

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
