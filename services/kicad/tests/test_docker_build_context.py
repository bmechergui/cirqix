"""Regression guards for pinned Circuit-Synth Docker sources."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SERVICE_DIR = ROOT / "services" / "kicad"
CIRCUIT_SYNTH_PATH = "services/kicad/circuit_synth"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


class DockerBuildContextTests(unittest.TestCase):
    def test_circuit_synth_is_a_tracked_public_submodule(self) -> None:
        staged = _git("ls-files", "--stage", "--", CIRCUIT_SYNTH_PATH)
        self.assertEqual(staged.returncode, 0, staged.stderr)
        self.assertRegex(
            staged.stdout.strip(),
            rf"^160000 [0-9a-f]{{40}} 0\s+{re.escape(CIRCUIT_SYNTH_PATH)}$",
            "circuit_synth must be pinned as a gitlink in clean CI checkouts",
        )

        ignored = _git("check-ignore", "--no-index", "-q", CIRCUIT_SYNTH_PATH)
        self.assertNotEqual(
            ignored.returncode,
            0,
            "the circuit_synth submodule path must not be gitignored",
        )

        gitmodules = (ROOT / ".gitmodules").read_text(encoding="utf-8")
        self.assertIn("path = services/kicad/circuit_synth", gitmodules)
        self.assertIn("url = https://github.com/bmechergui/circuit-synth.git", gitmodules)

    def test_docker_uses_python_312_compatible_kicad_base(self) -> None:
        dockerfile = (SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM ubuntu:24.04 AS base", dockerfile)
        self.assertIn("/ubuntu noble main", dockerfile)
        self.assertRegex(
            dockerfile,
            r"sys\.version_info\s*>=\s*\(3,\s*12\)",
            "Docker must fail fast unless Circuit-Synth's Python requirement is met",
        )
        self.assertRegex(
            dockerfile,
            r"circuit_synth\.__version__\s*==\s*['\"]0\.12\.1['\"]",
            "Docker must smoke-test the pinned Circuit-Synth release",
        )

    def test_kicad_docker_job_is_blocking(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        match = re.search(
            r"(?ms)^  kicad-docker:\s*\n(.*?)(?=^  [A-Za-z0-9_-]+:\s*$|\Z)",
            workflow,
        )
        self.assertIsNotNone(match, "kicad-docker CI job not found")
        assert match is not None
        job = match.group(1)
        self.assertNotIn("continue-on-error: true", job)
        self.assertIn("submodules: true", job)
        self.assertNotIn("submodules: recursive", job)
        self.assertIn("test_cirqix_*.py", job)
        self.assertIn(".State.Health.Status", job)
        self.assertNotIn("sleep 10", job)

    def test_docker_context_excludes_environment_files(self) -> None:
        patterns = {
            line.strip()
            for line in (SERVICE_DIR / ".dockerignore").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn(".env", patterns)
        self.assertIn(".env.*", patterns)


if __name__ == "__main__":
    unittest.main()
