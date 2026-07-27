from unittest.mock import MagicMock

from app.core.ids import uuid7
from app.etl.lifecycle import TaskOperation
from app.infrastructure.db.models.knowledge import Document, DocumentVersion, KnowledgeBase
from app.infrastructure.db.models.tasks import AsyncTask
from app.infrastructure.db.repositories.lifecycle import SQLAlchemyLifecycleRepository


def test_claim_derives_tenant_and_knowledge_base_from_database_relationships() -> None:
    tenant_id = uuid7()
    knowledge_base_id = uuid7()
    document_id = uuid7()
    version_id = uuid7()
    task_id = uuid7()
    task = AsyncTask(
        id=task_id,
        task_type=TaskOperation.INGEST.value,
        resource_type="DOCUMENT",
        resource_id=document_id,
        status="PENDING",
        stage="QUEUED",
        progress=0,
        attempt_count=0,
        max_attempts=3,
    )
    knowledge_base = KnowledgeBase(id=knowledge_base_id, tenant_id=tenant_id)
    document = Document(
        id=document_id,
        knowledge_base_id=knowledge_base_id,
        current_version_no=1,
        source_key="document.txt",
        mime_type="text/plain",
    )
    version = DocumentVersion(
        id=version_id,
        document_id=document_id,
        version_no=1,
        file_uri="document.txt",
        file_sha256="a" * 64,
        file_size=10,
        cleaning_config_json={},
        splitter_config_json={"strategy": "recursive"},
    )
    session = MagicMock()
    session.scalar.side_effect = [task, version]
    session.execute.return_value.one_or_none.return_value = (document, knowledge_base)
    session_factory = MagicMock()
    session_factory.begin.return_value.__enter__.return_value = session

    job = SQLAlchemyLifecycleRepository(session_factory).claim(
        task_id, TaskOperation.INGEST, worker_id="worker-1"
    )

    assert job is not None
    assert job.tenant_id == tenant_id
    assert job.knowledge_base_id == knowledge_base_id
    assert job.document_id == document_id
    assert job.document_version_id == version_id


def test_claim_uses_task_target_version_instead_of_newer_current_version() -> None:
    tenant_id = uuid7()
    knowledge_base_id = uuid7()
    document_id = uuid7()
    version_id = uuid7()
    task_id = uuid7()
    task = AsyncTask(
        id=task_id,
        task_type=TaskOperation.INGEST.value,
        resource_type="DOCUMENT",
        resource_id=document_id,
        target_version_no=1,
        status="PENDING",
        stage="QUEUED",
        progress=0,
        attempt_count=0,
        max_attempts=3,
    )
    knowledge_base = KnowledgeBase(id=knowledge_base_id, tenant_id=tenant_id)
    document = Document(
        id=document_id,
        knowledge_base_id=knowledge_base_id,
        current_version_no=2,
        source_key="document.txt",
        mime_type="text/plain",
    )
    version = DocumentVersion(
        id=version_id,
        document_id=document_id,
        version_no=1,
        file_uri="document-v1.txt",
        file_sha256="a" * 64,
        file_size=10,
        cleaning_config_json={},
        splitter_config_json={"strategy": "recursive"},
    )
    session = MagicMock()
    session.scalar.side_effect = [task, version]
    session.execute.return_value.one_or_none.return_value = (document, knowledge_base)
    session_factory = MagicMock()
    session_factory.begin.return_value.__enter__.return_value = session

    job = SQLAlchemyLifecycleRepository(session_factory).claim(
        task_id, TaskOperation.INGEST, worker_id="worker-1"
    )

    assert job is not None
    assert job.document_version_id == version_id
    version_query = session.scalar.call_args_list[1].args[0]
    assert "document_versions.version_no =" in str(version_query)


def test_claim_fails_task_whose_document_no_longer_exists() -> None:
    task_id = uuid7()
    task = AsyncTask(
        id=task_id,
        task_type=TaskOperation.REBUILD.value,
        resource_type="DOCUMENT",
        resource_id=uuid7(),
        status="PENDING",
        stage="QUEUED",
        progress=0,
        attempt_count=0,
        max_attempts=3,
    )
    session = MagicMock()
    session.scalar.return_value = task
    session.execute.return_value.one_or_none.return_value = None
    session_factory = MagicMock()
    session_factory.begin.return_value.__enter__.return_value = session

    job = SQLAlchemyLifecycleRepository(session_factory).claim(
        task_id, TaskOperation.REBUILD, worker_id="worker-1"
    )

    assert job is None
    assert task.status == "FAILED"
    assert task.error_code == "TASK_RESOURCE_NOT_FOUND"
