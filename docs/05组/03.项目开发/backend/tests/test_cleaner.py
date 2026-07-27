from io import BytesIO

import pytest

from app.etl import (
    CleaningConfigError,
    CleaningFunctionRegistry,
    CleanStatus,
    ConfigurableCleaner,
    CsvLoader,
    RowTemplateError,
    TextLoader,
)


def records(csv: str):  # noqa: ANN201
    return list(CsvLoader().load(BytesIO(csv.encode()), source_key="reviews.csv"))


def test_configured_steps_run_in_order_and_report_counts() -> None:
    source = records(
        "merchant_id,merchant_name,rating,content,city\n"
        "1,青禾,4.8,环境   安静,成都\n"
        "1,青禾,4.8,环境   安静,成都\n"
        "2,木棉,5,,\n"
        "3,云间,4,适合聊天,\n"
    )
    cleaner = ConfigurableCleaner(
        [
            {"type": "dropna", "subset": ["content", "merchant_name"]},
            {"type": "fillna", "values": {"city": "未知"}},
            {"type": "regex", "column": "content", "pattern": r"\s+", "replace_with": " "},
            {"type": "drop_duplicates", "subset": ["merchant_id", "content"]},
        ],
        text_template="商家'{merchant_name}'收到评分{rating}的评价：{content}（{city}）",
    )

    cleaned = cleaner.clean(source)

    assert [item.content for item in cleaned] == [
        "商家'青禾'收到评分4.8的评价：环境 安静（成都）",
        "商家'云间'收到评分4的评价：适合聊天（未知）",
    ]
    assert all(item.clean_status is CleanStatus.CLEANED for item in cleaned)
    row_data = cleaned[1].metadata["row_data"]
    assert isinstance(row_data, dict)
    assert row_data["city"] == "未知"
    assert cleaner.last_report is not None
    assert cleaner.last_report.input_count == 4
    assert cleaner.last_report.output_count == 2
    assert [
        (step.step_type, step.input_count, step.output_count) for step in cleaner.last_report.steps
    ] == [
        ("dropna", 4, 3),
        ("fillna", 3, 3),
        ("regex", 3, 3),
        ("drop_duplicates", 3, 2),
        ("row_template", 2, 2),
    ]
    assert all(step.duration_ms >= 0 for step in cleaner.last_report.steps)


def test_regex_on_plain_content_refreshes_hash() -> None:
    [source] = list(TextLoader().load(BytesIO("环境   安静".encode()), source_key="review.txt"))
    old_hash = source.content_hash

    [cleaned] = ConfigurableCleaner(
        [{"type": "regex", "column": "content", "pattern": r"\s+", "replace_with": " "}]
    ).clean([source])

    assert cleaned.content == "环境 安静"
    assert cleaned.content_hash != old_hash


def test_custom_cleaner_must_be_registered_and_receives_options() -> None:
    registry = CleaningFunctionRegistry()
    registry.register(
        "suffix",
        lambda value, options: f"{value}{options['suffix']}" if value is not None else value,
    )
    cleaner = ConfigurableCleaner(
        [
            {
                "type": "custom",
                "name": "suffix",
                "column": "content",
                "options": {"suffix": "。"},
            }
        ],
        custom_functions=registry,
        text_template="{content}",
    )

    [cleaned] = cleaner.clean(records("content\n很好\n"))

    assert cleaned.content == "很好。"


def test_custom_errors_mark_review_and_capture_bounded_samples() -> None:
    registry = CleaningFunctionRegistry()

    def fail(value, options):  # noqa: ANN001, ANN202, ARG001
        raise ValueError("bad input")

    registry.register("fail", fail)
    cleaner = ConfigurableCleaner(
        [{"type": "custom", "name": "fail", "column": "content"}],
        custom_functions=registry,
        max_error_samples=1,
    )

    cleaned = cleaner.clean(records("content\na\nb\n"))

    assert all(item.clean_status is CleanStatus.REVIEW_REQUIRED for item in cleaned)
    assert cleaner.last_report is not None
    assert cleaner.last_report.steps[0].error_samples == ("reviews.csv#row=2",)


def test_unregistered_custom_cleaner_and_arbitrary_step_are_rejected() -> None:
    with pytest.raises(CleaningConfigError, match="not allowlisted"):
        ConfigurableCleaner([{"type": "custom", "name": "os.system", "column": "content"}])
    with pytest.raises(CleaningConfigError, match="unsupported"):
        ConfigurableCleaner([{"type": "import", "path": "package.function"}])


def test_row_template_reports_missing_fields_and_non_structured_records() -> None:
    with pytest.raises(RowTemplateError, match="missing"):
        ConfigurableCleaner([], text_template="{missing}").clean(records("content\n很好\n"))

    text_record = list(TextLoader().load(BytesIO(b"plain"), source_key="plain.txt"))
    with pytest.raises(RowTemplateError, match="row_data"):
        ConfigurableCleaner([], text_template="{content}").clean(text_record)


@pytest.mark.parametrize(
    "step",
    [
        {"type": "regex", "column": "content", "pattern": "["},
        {"type": "fillna", "subset": ["content"]},
        {"type": "dropna", "subset": []},
    ],
)
def test_invalid_cleaning_configuration_fails_early(step: dict[str, object]) -> None:
    with pytest.raises(CleaningConfigError):
        ConfigurableCleaner([step])


# ---------------------------------------------------------------------------
# Additional config validation error paths
# ---------------------------------------------------------------------------


def test_registry_rejects_blank_function_name() -> None:
    registry = CleaningFunctionRegistry()
    with pytest.raises(CleaningConfigError, match="must not be blank"):
        registry.register("  ", lambda v, o: v)


def test_registry_rejects_duplicate_function_name() -> None:
    registry = CleaningFunctionRegistry()
    registry.register("my_func", lambda v, o: v)
    with pytest.raises(CleaningConfigError, match="already registered"):
        registry.register("my_func", lambda v, o: v)


def test_configurable_cleaner_rejects_negative_max_error_samples() -> None:
    with pytest.raises(CleaningConfigError, match="greater than or equal to zero"):
        ConfigurableCleaner([], max_error_samples=-1)


def test_regex_step_rejects_blank_column() -> None:
    with pytest.raises(CleaningConfigError, match="non-blank string"):
        ConfigurableCleaner([{"type": "regex", "column": "", "pattern": ".*"}])


def test_regex_step_rejects_non_string_pattern() -> None:
    with pytest.raises(CleaningConfigError, match="must be a string"):
        ConfigurableCleaner([{"type": "regex", "column": "content", "pattern": 42}])


def test_fillna_step_rejects_empty_values_mapping() -> None:
    with pytest.raises(CleaningConfigError, match="non-empty mapping"):
        ConfigurableCleaner([{"type": "fillna", "values": {}}])


def test_custom_step_rejects_blank_name() -> None:
    with pytest.raises(CleaningConfigError, match="non-blank string"):
        ConfigurableCleaner([{"type": "custom", "name": "  ", "column": "content"}])


def test_custom_step_rejects_blank_column() -> None:
    with pytest.raises(CleaningConfigError, match="non-blank string"):
        ConfigurableCleaner([{"type": "custom", "name": "func", "column": ""}])


def test_custom_step_rejects_non_mapping_options() -> None:
    registry = CleaningFunctionRegistry()
    registry.register("func", lambda v, o: v)
    cleaner = ConfigurableCleaner(
        [{"type": "custom", "name": "func", "column": "content", "options": "bad"}],
        custom_functions=registry,
    )
    with pytest.raises(CleaningConfigError, match="must be a mapping"):
        cleaner.clean(records("content\n很好\n"))


def test_columns_rejects_invalid_type() -> None:
    from app.etl.cleaner import _columns

    with pytest.raises(CleaningConfigError, match="non-empty string list"):
        _columns({"subset": 123})


# ---------------------------------------------------------------------------
# _value / _with_value edge cases (previously uncovered)
# ---------------------------------------------------------------------------


def test_value_reads_source_key_from_record() -> None:
    from app.etl.cleaner import _value

    record = next(TextLoader().load(BytesIO(b"plain"), source_key="my-key.txt"))
    assert _value(record, "source_key") == "my-key.txt"


def test_value_reads_metadata_fallback() -> None:
    from app.etl.cleaner import _value

    record = next(TextLoader().load(BytesIO(b"plain"), source_key="key.txt"))
    assert _value(record, "non_existent") is None


def test_with_value_rejects_source_key_change() -> None:
    from app.etl.cleaner import _with_value

    record = next(TextLoader().load(BytesIO(b"plain"), source_key="key.txt"))
    with pytest.raises(CleaningConfigError, match="source_key cannot be changed"):
        _with_value(record, "source_key", "new-value")


def test_with_value_sets_metadata_column() -> None:
    from app.etl.cleaner import _with_value

    record = next(TextLoader().load(BytesIO(b"plain"), source_key="key.txt"))
    result = _with_value(record, "custom_meta", "meta-value")
    assert result.metadata["custom_meta"] == "meta-value"


def test_fillna_step_with_subset_requires_value() -> None:
    with pytest.raises(CleaningConfigError, match="requires value or values"):
        ConfigurableCleaner([{"type": "fillna", "subset": ["content"]}])


def test_fillna_step_rejects_non_string_key_in_values() -> None:
    cleaner = ConfigurableCleaner([{"type": "fillna", "values": {123: "x"}}])
    with pytest.raises(CleaningConfigError, match="keys must be strings"):
        cleaner.clean(records("content\n很好\n"))


def test_regex_step_rejects_non_string_replace_with() -> None:
    with pytest.raises(CleaningConfigError, match="replace_with must be a string"):
        ConfigurableCleaner(
            [{"type": "regex", "column": "content", "pattern": ".*", "replace_with": 42}]
        ).clean(records("content\n很好\n"))


def test_columns_accepts_single_string() -> None:
    from app.etl.cleaner import _columns

    result = _columns({"column": "content"})
    assert result == ("content",)


def test_fillna_step_with_subset_and_value_passes_validation() -> None:
    cleaner = ConfigurableCleaner(
        [{"type": "fillna", "subset": ["city"], "value": "未知"}],
        text_template="{content}",
    )
    result = cleaner.clean(records("content,city\n很好,\n"))
    assert result[0].metadata.get("row_data", {}).get("city") == "未知"
