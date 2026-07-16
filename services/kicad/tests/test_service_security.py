"""Security regression tests for the KiCad service trust boundary."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from security import (  # noqa: E402
    require_service_auth,
)


def _minimal_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(require_service_auth)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/private")
    def private() -> dict[str, bool]:
        return {"ok": True}

    return app


class ServiceAuthenticationTests(unittest.TestCase):
    TOKEN = "expected-service-token-that-is-at-least-32-chars"

    def test_health_remains_public_without_a_token(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            response = TestClient(_minimal_app()).get("/health")

        self.assertEqual(response.status_code, 200)

    def test_private_routes_fail_closed_when_server_token_is_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            response = TestClient(_minimal_app()).post("/private")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "service_auth_not_configured")

    def test_private_routes_reject_missing_or_invalid_bearer_tokens(self) -> None:
        with patch.dict(os.environ, {"KICAD_SERVICE_TOKEN": self.TOKEN}, clear=True):
            client = TestClient(_minimal_app())
            missing = client.post("/private")
            invalid = client.post(
                "/private",
                headers={"Authorization": "Bearer wrong-token"},
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)

    def test_private_routes_accept_the_exact_bearer_token(self) -> None:
        with patch.dict(os.environ, {"KICAD_SERVICE_TOKEN": self.TOKEN}, clear=True):
            response = TestClient(_minimal_app()).post(
                "/private",
                headers={"Authorization": f"Bearer {self.TOKEN}"},
            )

        self.assertEqual(response.status_code, 200)

    def test_private_routes_fail_closed_when_server_token_is_too_short(self) -> None:
        with patch.dict(os.environ, {"KICAD_SERVICE_TOKEN": "short-token"}, clear=True):
            response = TestClient(_minimal_app()).post("/private")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "service_auth_not_configured")

    def test_real_app_protects_registered_schematic_routes(self) -> None:
        from main import app

        with patch.dict(os.environ, {"KICAD_SERVICE_TOKEN": self.TOKEN}, clear=False):
            client = TestClient(app)
            missing = client.post(
                "/schematic/validate-symbols",
                json={"components": []},
            )
            authorized = client.post(
                "/schematic/validate-symbols",
                json={"components": []},
                headers={"Authorization": f"Bearer {self.TOKEN}"},
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(authorized.status_code, 200)

    def test_real_app_rejects_project_id_path_traversal(self) -> None:
        from main import app

        headers = {"Authorization": f"Bearer {self.TOKEN}"}
        with patch.dict(os.environ, {"KICAD_SERVICE_TOKEN": self.TOKEN}, clear=False):
            client = TestClient(app)
            schematic = client.post(
                "/schematic/generate",
                json={"components": [], "nets": [], "project_id": "../../escape"},
                headers=headers,
            )
            export = client.post(
                "/export/all",
                json={"kicad_pcb_b64": "", "project_id": "../../escape"},
                headers=headers,
            )

        self.assertEqual(schematic.status_code, 422)
        self.assertEqual(export.status_code, 422)


class RuntimeHardeningTests(unittest.TestCase):
    def test_generated_python_execution_endpoint_is_not_registered(self) -> None:
        from routers.schematic import router

        self.assertNotIn("/schematic/execute", {route.path for route in router.routes})

    def test_docker_runtime_uses_a_non_root_user(self) -> None:
        dockerfile = (SERVICE_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?m)^USER\s+cirqix\s*$")


if __name__ == "__main__":
    unittest.main()
