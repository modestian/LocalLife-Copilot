from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DEPENDENCIES = {"mysql", "redis", "opensearch", "model-gateway"}
APPLICATION_SERVICES = {"api", "worker"}
REQUIRED_SERVICES = (
    RUNTIME_DEPENDENCIES
    | APPLICATION_SERVICES
    | {
        "migrate",
        "init",
        "frontend",
        "nginx",
    }
)
DEVELOPMENT_PORT_SERVICES = {"mysql", "redis", "opensearch", "api", "nginx"}


def load_yaml(name: str) -> dict:
    with (ROOT / name).open(encoding="utf-8") as compose_file:
        return yaml.safe_load(compose_file)


def main() -> None:
    base = load_yaml("compose.yaml")
    development = load_yaml("compose.override.yaml")
    services = base.get("services", {})
    missing = REQUIRED_SERVICES - services.keys()
    assert not missing, f"compose.yaml is missing services: {sorted(missing)}"

    for name in REQUIRED_SERVICES:
        assert "healthcheck" in services[name] or name in {"migrate", "init"}, (
            f"{name} must define a healthcheck"
        )
        assert "ports" not in services[name], (
            f"{name} must not publish ports in the base Compose file"
        )

    development_services = development.get("services", {})
    for name in DEVELOPMENT_PORT_SERVICES:
        development_ports = development_services[name].get("ports", [])
        assert development_ports, (
            f"{name} must publish ports in the development override"
        )
        assert all(str(port).startswith("127.0.0.1:") for port in development_ports), (
            f"{name} development ports must bind only to loopback"
        )

    migrate = services["migrate"]
    assert migrate["command"] == ["alembic", "upgrade", "head"], (
        "migrate must only execute the Alembic upgrade"
    )
    assert migrate["depends_on"] == {"mysql": {"condition": "service_healthy"}}, (
        "migrate must wait only for MySQL"
    )

    init = services["init"]
    assert init["command"] == ["python", "-m", "app.init_runtime"]
    assert (
        init["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    )
    assert init["depends_on"]["opensearch"]["condition"] == "service_healthy"

    for service_name in APPLICATION_SERVICES:
        dependencies = services[service_name]["depends_on"]
        assert dependencies["migrate"]["condition"] == "service_completed_successfully"
        assert dependencies["init"]["condition"] == "service_completed_successfully"
        for dependency in RUNTIME_DEPENDENCIES:
            assert dependencies[dependency]["condition"] == "service_healthy"

        service = services[service_name]
        assert service.get("read_only") is True
        assert "no-new-privileges:true" in service.get("security_opt", [])
        assert all("docker.sock" not in str(volume) for volume in service.get("volumes", []))

    assert base["networks"]["backend"].get("internal") is True
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    assert "FROM base AS runtime" in dockerfile
    assert "USER app" in dockerfile

    nginx_dependencies = services["nginx"]["depends_on"]
    assert nginx_dependencies["api"]["condition"] == "service_healthy"
    assert nginx_dependencies["frontend"]["condition"] == "service_healthy"

    nginx_config = (ROOT / "deploy/nginx/nginx.conf").read_text(encoding="utf-8")
    for directive in (
        "proxy_set_header Upgrade $http_upgrade;",
        "proxy_buffering off;",
        "proxy_cache off;",
        "proxy_read_timeout 3600s;",
        "add_header X-Accel-Buffering no always;",
    ):
        assert directive in nginx_config, (
            f"Nginx streaming directive is missing: {directive}"
        )


if __name__ == "__main__":
    main()
