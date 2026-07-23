from app.main import create_app

EXPECTED_OPERATIONS = {
    ("post", "/api/v1/knowledge-bases/{knowledge_base_id}/data-sources"),
    ("post", "/api/v1/data-sources/{data_source_id}/ingest"),
    ("get", "/api/v1/merchants"),
    ("get", "/api/v1/merchants/{merchant_id}"),
    ("get", "/api/v1/merchants/{merchant_id}/reviews"),
    ("post", "/api/v1/merchants/{merchant_id}/analysis-jobs"),
    ("post", "/api/v1/fine-tuning/jobs"),
    ("get", "/api/v1/fine-tuning/jobs/{job_id}"),
    ("post", "/api/v1/fine-tuning/jobs/{job_id}/cancel"),
    ("post", "/api/v1/fine-tuning/jobs/{job_id}/evaluate"),
    ("post", "/api/v1/fine-tuning/jobs/{job_id}/register-model"),
    ("post", "/api/v1/knowledge-bases/{knowledge_base_id}/clone"),
    ("get", "/api/v1/documents/{document_id}/preview"),
    ("get", "/api/v1/merchants/{merchant_id}/sentiment"),
    ("get", "/api/v1/merchants/{merchant_id}/topics"),
    ("get", "/api/v1/moderation/cases"),
    ("post", "/api/v1/moderation/cases/{case_id}/decision"),
    ("get", "/api/v1/analytics/overview"),
}


def test_all_missing_operations_are_registered_in_openapi() -> None:
    schema = create_app(readiness_checks={}).openapi()
    registered = {
        (method, path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }

    assert EXPECTED_OPERATIONS <= registered


def test_async_operations_use_accepted_status_codes() -> None:
    schema = create_app(readiness_checks={}).openapi()
    accepted_operations = {
        "/api/v1/data-sources/{data_source_id}/ingest",
        "/api/v1/merchants/{merchant_id}/analysis-jobs",
        "/api/v1/fine-tuning/jobs",
        "/api/v1/fine-tuning/jobs/{job_id}/evaluate",
        "/api/v1/knowledge-bases/{knowledge_base_id}/clone",
    }

    for path in accepted_operations:
        assert "202" in schema["paths"][path]["post"]["responses"]
