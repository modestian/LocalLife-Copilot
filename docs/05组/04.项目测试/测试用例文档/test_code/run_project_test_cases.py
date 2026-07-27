"""Run project-native automated evidence by XLSX case domain.

This runner intentionally calls the repository's existing pytest, Vitest,
Playwright, Compose, performance, and recovery assets. It does not duplicate
their fixtures or weaken their environment gates.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Command:
    name: str
    cwd: Path
    argv: tuple[str, ...]


PYTHON = os.getenv("LOCAL_LIFE_PYTHON", sys.executable)
NPM = shutil.which("npm") or "npm"
DOCKER = shutil.which("docker") or "docker"

GROUPS: dict[str, tuple[Command, ...]] = {
    "AUTH": (
        Command(
            "AUTH-01~06 backend",
            REPO_ROOT / "backend",
            (
                PYTHON,
                "-m",
                "pytest",
                "tests/test_auth.py",
                "tests/test_authorization.py",
                "tests/test_login_rate_limit.py",
                "tests/test_websocket_tokens.py",
                "-q",
            ),
        ),
        Command(
            "AUTH frontend routing/store",
            REPO_ROOT / "frontend",
            (NPM, "test", "--", "src/router/auth-routing.test.ts", "src/stores/auth.test.ts"),
        ),
    ),
    "KB": (
        Command(
            "KB-01~07 backend",
            REPO_ROOT / "backend",
            (
                PYTHON,
                "-m",
                "pytest",
                "tests/test_knowledge_service.py",
                "tests/test_file_loaders.py",
                "tests/test_ingestion_acceptance.py",
                "tests/test_security_upload.py",
                "tests/test_task_state_machine.py",
                "tests/test_task_repositories.py",
                "tests/test_search_indexes.py",
                "-q",
            ),
        ),
        Command(
            "KB frontend",
            REPO_ROOT / "frontend",
            (
                NPM,
                "test",
                "--",
                "src/components/DocumentUploadPanel.test.ts",
                "src/components/KnowledgeDocumentWorkspace.test.ts",
                "src/views/admin/KnowledgeBaseDetailView.test.ts",
            ),
        ),
    ),
    "GOV": (
        Command(
            "GOV-01 configuration, logging, and audit governance",
            REPO_ROOT / "backend",
            (
                PYTHON,
                "-m",
                "pytest",
                "tests/test_config.py",
                "tests/test_observability.py",
                "tests/test_governance_versions.py",
                "tests/test_governance_safety.py",
                "tests/test_governance_api.py",
                "-q",
            ),
        ),
    ),
    "SEARCH": (
        Command(
            "SEARCH-01~02 backend",
            REPO_ROOT / "backend",
            (
                PYTHON,
                "-m",
                "pytest",
                "tests/test_search_api.py",
                "tests/test_search_pipeline.py",
                "tests/test_search_scope.py",
                "tests/test_search_ranking.py",
                "tests/test_search_retrieval.py",
                "-q",
            ),
        ),
        Command(
            "SEARCH frontend",
            REPO_ROOT / "frontend",
            (
                NPM,
                "test",
                "--",
                "src/api/search.test.ts",
                "src/components/RetrievalDebugPanel.test.ts",
            ),
        ),
    ),
    "RAG": (
        Command(
            "RAG-01~04 backend",
            REPO_ROOT / "backend",
            (
                PYTHON,
                "-m",
                "pytest",
                "tests/test_agent_runtime.py",
                "tests/test_agent_citations.py",
                "tests/test_conversation_memory.py",
                "tests/test_chat_knowledge.py",
                "tests/test_recommendation_generator.py",
                "-q",
            ),
        ),
        Command(
            "RAG frontend",
            REPO_ROOT / "frontend",
            (
                NPM,
                "test",
                "--",
                "src/components/ConversationWorkspace.test.ts",
                "src/components/WebSocketChatPanel.test.ts",
                "src/components/RecommendationResults.test.ts",
            ),
        ),
    ),
    "WS": (
        Command(
            "WS-01~02 backend",
            REPO_ROOT / "backend",
            (
                PYTHON,
                "-m",
                "pytest",
                "tests/test_websocket_tokens.py",
                "tests/test_websocket_chat.py",
                "tests/test_websocket_recommendations.py",
                "tests/test_openai_compat.py",
                "tests/test_chat_transports_integration.py",
                "-q",
            ),
        ),
        Command(
            "WS frontend",
            REPO_ROOT / "frontend",
            (
                NPM,
                "test",
                "--",
                "src/composables/useWebSocketChat.test.ts",
                "src/components/WebSocketChatPanel.test.ts",
            ),
        ),
    ),
    "MERCHANT": (
        Command(
            "MERCHANT backend",
            REPO_ROOT / "backend",
            (
                PYTHON,
                "-m",
                "pytest",
                "tests/test_analytics.py",
                "tests/test_user_reviews.py",
                "tests/test_reply_generator.py",
                "tests/test_recommendation_generator.py",
                "-q",
            ),
        ),
        Command(
            "MERCHANT frontend",
            REPO_ROOT / "frontend",
            (
                NPM,
                "test",
                "--",
                "src/components/MerchantAnalyticsDashboard.test.ts",
                "src/components/MerchantInsightWorkbench.test.ts",
            ),
        ),
    ),
    "MODEL": (
        Command(
            "MODEL backend",
            REPO_ROOT / "backend",
            (
                PYTHON,
                "-m",
                "pytest",
                "tests/test_feedback_service.py",
                "tests/test_feedback_pii_quality.py",
                "tests/test_dataset_builder.py",
                "tests/test_train_lora.py",
                "tests/test_governance.py",
                "tests/test_governance_api.py",
                "-q",
            ),
        ),
        Command(
            "MODEL frontend",
            REPO_ROOT / "frontend",
            (
                NPM,
                "test",
                "--",
                "src/components/MessageFeedbackControl.test.ts",
                "src/components/ModelLifecycleWorkbench.test.ts",
            ),
        ),
    ),
    "UI": (
        Command(
            "UI unit/component",
            REPO_ROOT / "frontend",
            (
                NPM,
                "test",
                "--",
                "src/router/guest-routing.test.ts",
                "src/utils/safe-markdown.test.ts",
                "src/responsive-layout.test.ts",
            ),
        ),
        Command(
            "UI Playwright",
            REPO_ROOT / "frontend",
            (
                NPM,
                "run",
                "test:e2e",
                "--",
                "--config",
                "../docs/测试用例文档/test_code/playwright.delivery.config.ts",
                "responsive-user-workspace.spec.ts",
            ),
        ),
    ),
    "ADMIN": (
        Command(
            "ADMIN-01 knowledge-base and task management UI",
            REPO_ROOT / "frontend",
            (
                NPM,
                "test",
                "--",
                "src/views/admin/KnowledgeBaseListView.test.ts",
                "src/views/admin/KnowledgeBaseDetailView.test.ts",
                "src/components/DocumentUploadPanel.test.ts",
                "src/components/KnowledgeDocumentWorkspace.test.ts",
                "src/components/TaskProgressCard.test.ts",
                "src/api/knowledge-bases.test.ts",
                "src/api/documents.test.ts",
                "src/api/tasks.test.ts",
            ),
        ),
    ),
    "OPS": (
        Command("Compose model", REPO_ROOT, (DOCKER, "compose", "config", "--quiet")),
        Command("Compose policy", REPO_ROOT, (PYTHON, "scripts/verify_compose.py")),
        Command(
            "OPS backend",
            REPO_ROOT / "backend",
            (
                PYTHON,
                "-m",
                "pytest",
                "tests/test_health.py",
                "tests/test_observability.py",
                "tests/test_storage_recovery.py",
                "tests/test_performance_gate.py",
                "-q",
            ),
        ),
    ),
    "E2E": (
        Command(
            "E2E-01 deterministic seed evidence",
            REPO_ROOT / "backend",
            (
                PYTHON,
                "-m",
                "pytest",
                "tests/test_seed_demo_data.py",
                "tests/test_seed_merchant_data.py",
                "-q",
            ),
        ),
        Command(
            "E2E-01 core role flows",
            REPO_ROOT / "frontend",
            (
                NPM,
                "run",
                "test:e2e",
                "--",
                "--config",
                "../docs/测试用例文档/test_code/playwright.delivery.config.ts",
                "st-702-core-flows.spec.ts",
            ),
        ),
    ),
    "DELIVERY": (
        Command(
            "Test-delivery consistency",
            REPO_ROOT,
            (
                PYTHON,
                "-m",
                "pytest",
                "docs/测试用例文档/test_code/test_delivery_consistency.py",
                "-q",
            ),
        ),
    ),
    "SMOKE": (
        Command(
            "Release-candidate black-box smoke",
            REPO_ROOT,
            (
                PYTHON,
                "-m",
                "pytest",
                "docs/测试用例文档/test_code/test_release_candidate_smoke.py",
                "-q",
            ),
        ),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("groups", nargs="*", choices=sorted(GROUPS))
    parser.add_argument("--all", action="store_true", help="Run every evidence group")
    parser.add_argument("--list", action="store_true", help="Print commands without running them")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument(
        "--result-dir",
        type=Path,
        help="Write one UTF-8 log per command plus summary.json/summary.md",
    )
    return parser.parse_args()


def _safe_slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip(
        "-"
    )


def _redact(value: str) -> str:
    for variable in (
        "DEMO_SEED_PASSWORD",
        "LOCAL_LIFE_TEST_PASSWORD",
        "PERF_PASSWORD",
        "BACKUP_ENCRYPTION_PASSWORD",
    ):
        secret = os.getenv(variable)
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


def _run_and_tee(command: Command, log_path: Path | None) -> int:
    environment = os.environ.copy()
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        process = subprocess.Popen(
            command.argv,
            cwd=command.cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        message = f"BLOCKED: executable not found: {exc.filename}\n"
        print(f"  {message}", file=sys.stderr, end="")
        if log_path is not None:
            log_path.write_text(message, encoding="utf-8")
        return 127

    assert process.stdout is not None
    log_file = log_path.open("w", encoding="utf-8", newline="") if log_path else None
    try:
        for line in process.stdout:
            safe_line = _redact(line)
            print(safe_line, end="", flush=True)
            if log_file is not None:
                log_file.write(safe_line)
    finally:
        if log_file is not None:
            log_file.close()
    return process.wait()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    groups = list(GROUPS) if args.all else (args.groups or ["SMOKE"])
    commands = [(group, command) for group in groups for command in GROUPS[group]]
    result_dir = args.result_dir.resolve() if args.result_dir else None
    if result_dir is not None:
        result_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    overall_return_code = 0
    for index, (group, command) in enumerate(commands, start=1):
        printable = subprocess.list2cmdline(command.argv)
        print(f"[{command.name}] cwd={command.cwd}\n  {printable}", flush=True)
        if args.list:
            continue
        started_at = datetime.now(timezone.utc)
        log_path = (
            result_dir / f"{index:02d}-{group.lower()}-{_safe_slug(command.name)}.log"
            if result_dir
            else None
        )
        return_code = _run_and_tee(command, log_path)
        finished_at = datetime.now(timezone.utc)
        records.append(
            {
                "group": group,
                "name": command.name,
                "cwd": str(command.cwd),
                "command": list(command.argv),
                "started_at_utc": started_at.isoformat(),
                "finished_at_utc": finished_at.isoformat(),
                "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
                "exit_code": return_code,
                "status": "PASS" if return_code == 0 else "FAIL",
                "log": log_path.name if log_path else None,
            }
        )
        if return_code:
            overall_return_code = overall_return_code or return_code
            if not args.continue_on_failure:
                break
    if result_dir is not None and not args.list:
        passed = sum(record["status"] == "PASS" for record in records)
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "groups": groups,
            "commands_total": len(records),
            "commands_passed": passed,
            "commands_failed": len(records) - passed,
            "overall_status": "PASS" if overall_return_code == 0 else "FAIL",
            "results": records,
        }
        (result_dir / "summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        lines = [
            "# 项目自动化测试执行汇总",
            "",
            f"- 生成时间（UTC）：{payload['generated_at_utc']}",
            f"- 命令数：{len(records)}",
            f"- 通过：{passed}",
            f"- 失败：{len(records) - passed}",
            f"- 总体结果：**{payload['overall_status']}**",
            "",
            "| 分组 | 执行项 | 结果 | 耗时（秒） | 日志 |",
            "|---|---|---:|---:|---|",
        ]
        for record in records:
            lines.append(
                f"| {record['group']} | {record['name']} | {record['status']} | "
                f"{record['duration_seconds']} | {record['log']} |"
            )
        (result_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return overall_return_code


if __name__ == "__main__":
    raise SystemExit(main())
