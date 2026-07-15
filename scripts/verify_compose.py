from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = {"mysql", "redis", "opensearch"}
REQUIRED_SERVICES = DEPENDENCIES | {"migrate", "api", "frontend"}


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
        assert "healthcheck" in services[name] or name == "migrate", (
            f"{name} must define a healthcheck"
        )

    for name in DEPENDENCIES:
        assert "ports" not in services[name], (
            f"{name} must not publish ports in the base Compose file"
        )
        development_ports = development["services"][name].get("ports", [])
        assert development_ports, f"{name} must publish ports in the development override"
        assert all(str(port).startswith('127.0.0.1:') for port in development_ports), (
            f"{name} development ports must bind only to loopback"
        )

    api_dependencies = services["api"]["depends_on"]
    assert api_dependencies["migrate"]["condition"] == "service_completed_successfully"
    for name in DEPENDENCIES:
        assert api_dependencies[name]["condition"] == "service_healthy"


if __name__ == "__main__":
    main()

