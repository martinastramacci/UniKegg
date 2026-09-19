"""Static checks complement, but do not replace, container execution in CI."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_services_and_initialization():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {"mysql", "etl"}
    assert services["mysql"]["image"] == "mysql:8.0.44"
    assert services["etl"]["depends_on"]["mysql"]["condition"] == "service_healthy"
    assert "./db/init:/docker-entrypoint-initdb.d:ro" in services["mysql"]["volumes"]
    assert services["etl"]["environment"]["MYSQL_HOST"] == "mysql"
    assert services["mysql"]["ports"][0].startswith("127.0.0.1:")
    assert "mysql_data" in compose["volumes"]


def test_workflow_uses_container_integration():
    workflow = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    assert {"push", "pull_request", "workflow_dispatch"} <= set(workflow["on"])
    job = workflow["jobs"]["mysql-integration"]
    assert job["env"]["UNIKEGG_DATASET_KIND"] == "synthetic"
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "docker compose up --build -d" in commands
    assert "docker compose run --rm etl verify" in commands
    assert "docker compose down --volumes" in commands
