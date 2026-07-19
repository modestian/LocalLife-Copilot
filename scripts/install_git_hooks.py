"""Install repository-managed quality hooks into the current Git clone."""

import shutil
import stat
import subprocess
from pathlib import Path


def git_path(name: str) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-path", name],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    source_directory = repository_root / "scripts" / "git_hooks"
    hooks_directory = git_path("hooks")
    hooks_directory.mkdir(parents=True, exist_ok=True)

    for hook_name in ("pre-commit", "pre-push"):
        source = source_directory / hook_name
        target = hooks_directory / hook_name
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise RuntimeError(
                f"Refusing to overwrite existing hook: {target}. "
                "Merge it with the repository hook manually."
            )
        shutil.copyfile(source, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"Installed {hook_name}: {target}")


if __name__ == "__main__":
    main()
