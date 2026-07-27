from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_docker_compose_defines_api_and_postgres_services() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

    assert set(compose["services"]) == {"api", "postgres"}
    api = compose["services"]["api"]
    assert api["build"]["context"] == "./backend"
    assert api["ports"] == ["8000:8000"]
    assert api["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert api["env_file"] == ["./backend/.env"]


def test_docker_compose_uses_container_safe_runtime_environment() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = compose["services"]["api"]["environment"]

    assert environment["HOST"] == "0.0.0.0"
    assert environment["PORT"] == "8000"
    assert environment["POSTGRES_URL"] == "postgresql://zoey:zoey@postgres:5432/zoey_agent"
    assert environment["EMBEDDING_BASE_URL"] == "http://host.docker.internal:11434"
    assert environment["AMAP_MCP_COMMAND"] == "amap-mcp-server"
    assert "\\" not in environment["AMAP_MCP_COMMAND"]


def test_backend_dockerfile_installs_requirements_and_runs_uvicorn() -> None:
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt" in dockerfile
    assert "COPY tests ./tests" in dockerfile
    assert 'CMD ["python", "-m", "uvicorn", "app.api.main:app"' in dockerfile


def test_backend_dockerignore_excludes_local_noise_and_secrets() -> None:
    dockerignore = (ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")

    for ignored in [".env", "__pycache__/", ".pytest_cache/"]:
        assert ignored in dockerignore
    assert "tests/" not in dockerignore
