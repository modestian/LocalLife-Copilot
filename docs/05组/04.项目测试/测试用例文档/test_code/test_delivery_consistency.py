"""Consistency checks for the generated test-report delivery bundle."""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree


REPO_ROOT = Path(__file__).resolve().parents[3]
DELIVERY_DIR = Path(__file__).resolve().parent.parent
WORKBOOK = DELIVERY_DIR / "LocalLife-Copilot测试用例清单.xlsx"
REPORT = DELIVERY_DIR / "LocalLife-Copilot测试总结报告-V2.0-执行版.docx"
RUNNER = Path(__file__).with_name("run_project_test_cases.py")

EXPECTED_STORIES = {
    "ST-101",
    "ST-102",
    "ST-103",
    "ST-201",
    "ST-202",
    "ST-301",
    "ST-302",
    "ST-401",
    "ST-402",
    "ST-501",
    "ST-502",
    "ST-601",
    "ST-602",
    "ST-603",
    "ST-701",
    "ST-702",
    "ST-703",
}
EXPECTED_GROUPS = {
    "AUTH",
    "KB",
    "GOV",
    "SEARCH",
    "RAG",
    "WS",
    "MERCHANT",
    "MODEL",
    "UI",
    "ADMIN",
    "OPS",
    "E2E",
    "DELIVERY",
    "SMOKE",
}

MAIN_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {
    "r": "http://schemas.openxmlformats.org/package/2006/relationships",
    "o": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _xlsx_rows() -> list[list[str]]:
    with zipfile.ZipFile(WORKBOOK) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(node.text or "" for node in item.findall(".//x:t", MAIN_NS))
                for item in root.findall("x:si", MAIN_NS)
            ]

        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = workbook.find("x:sheets/x:sheet", MAIN_NS)
        assert first_sheet is not None
        relationship_id = first_sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        relationships = ElementTree.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
        target = next(
            item.attrib["Target"]
            for item in relationships.findall("r:Relationship", REL_NS)
            if item.attrib["Id"] == relationship_id
        )
        if target.startswith("/"):
            sheet_path = target.lstrip("/")
        elif target.startswith("xl/"):
            sheet_path = target
        else:
            sheet_path = "xl/" + target
        sheet = ElementTree.fromstring(archive.read(sheet_path))

        rows: list[list[str]] = []
        for row in sheet.findall(".//x:sheetData/x:row", MAIN_NS):
            values: dict[int, str] = {}
            for cell in row.findall("x:c", MAIN_NS):
                column_letters = re.match(r"[A-Z]+", cell.attrib["r"])
                assert column_letters is not None
                column = 0
                for letter in column_letters.group():
                    column = column * 26 + ord(letter) - ord("A") + 1
                value_node = cell.find("x:v", MAIN_NS)
                value = "" if value_node is None else (value_node.text or "")
                if cell.attrib.get("t") == "s" and value:
                    value = shared_strings[int(value)]
                elif cell.attrib.get("t") == "inlineStr":
                    value = "".join(
                        node.text or "" for node in cell.findall(".//x:t", MAIN_NS)
                    )
                values[column] = value
            if values:
                rows.append([values.get(index, "") for index in range(1, max(values) + 1)])
        return rows


def _case_rows() -> list[list[str]]:
    rows = _xlsx_rows()
    header_index = next(
        index for index, row in enumerate(rows) if row and row[0] == "用例ID"
    )
    return [
        row
        for row in rows[header_index + 1 :]
        if row and re.fullmatch(r"[A-Z0-9]+-\d{2}", row[0])
    ]


def _docx_text() -> str:
    with zipfile.ZipFile(REPORT) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    return "".join(node.text or "" for node in root.findall(".//w:t", WORD_NS))


def test_workbook_covers_every_story_once_or_more() -> None:
    cases = _case_rows()
    assert len(cases) == 49
    assert len({row[0] for row in cases}) == 49
    assert {row[2] for row in cases} == EXPECTED_STORIES
    assert Counter(row[4] for row in cases) == {"P0": 37, "P1": 12}


def test_every_case_has_traceable_automation_and_result_columns() -> None:
    for row in _case_rows():
        assert len(row) >= 14
        assert row[10]
        assert row[11]
        assert row[12]
        assert row[13] in {"未执行", "通过", "失败", "阻塞", "不适用"}


def test_summary_report_matches_workbook_counts() -> None:
    text = _docx_text()
    assert "共49项：P0 37项、P1 12项" in text
    assert "覆盖7个Epic、17个Story" in text
    assert "48 条通过、1 条阻塞" in text
    for story in ("ST-103", "ST-602", "ST-702"):
        assert story in text


def test_runner_exposes_all_documented_evidence_groups() -> None:
    namespace: dict[str, object] = {"__file__": str(RUNNER)}
    exec(compile(RUNNER.read_text(encoding="utf-8"), str(RUNNER), "exec"), namespace)
    groups = namespace["GROUPS"]
    assert isinstance(groups, dict)
    assert set(groups) == EXPECTED_GROUPS
    for commands in groups.values():
        for command in commands:
            assert Path(command.cwd).exists()
            for argument in command.argv:
                if not isinstance(argument, str):
                    continue
                if argument.startswith(("tests/", "src/", "docs/", "scripts/")):
                    assert (Path(command.cwd) / argument).exists(), argument


def test_referenced_delivery_files_exist() -> None:
    assert WORKBOOK.is_file()
    assert REPORT.is_file()
    assert (DELIVERY_DIR / "交付说明与执行结果.md").is_file()
    assert RUNNER.is_file()
    assert (Path(__file__).with_name("run_full_validation.ps1")).is_file()
    assert (REPO_ROOT / "scripts/run_tk703_performance.ps1").is_file()
    assert (REPO_ROOT / "scripts/run_tk703_recovery.ps1").is_file()
