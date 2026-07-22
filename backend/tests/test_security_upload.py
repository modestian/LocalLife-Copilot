import io
import zipfile

import pytest

from app.application.upload_security import UnsafeUploadError, validate_upload


def _office_archive(*entries: tuple[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def test_upload_accepts_supported_content_with_matching_signature() -> None:
    validated = validate_upload(
        "门店说明.pdf",
        "application/pdf",
        b"%PDF-1.7\nvalid test document",
        max_uncompressed_bytes=1024,
    )

    assert validated.filename == "门店说明.pdf"
    assert validated.safe_filename == "____.pdf"
    assert validated.mime_type == "application/pdf"


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("../escape.txt", "text/plain", b"data"),
        ("report.exe", "application/octet-stream", b"MZpayload"),
        ("report.pdf", "application/pdf", b"MZpayload"),
        ("report.pdf", "text/plain", b"%PDF-1.7"),
        ("report.txt", "text/plain", b"text\x00binary"),
    ],
)
def test_upload_rejects_path_traversal_executables_mime_spoofing_and_binary_text(
    filename: str, content_type: str, content: bytes
) -> None:
    with pytest.raises(UnsafeUploadError):
        validate_upload(
            filename,
            content_type,
            content,
            max_uncompressed_bytes=1024,
        )


def test_upload_rejects_office_archive_with_executable_payload() -> None:
    content = _office_archive(
        ("[Content_Types].xml", b"<Types />"),
        ("word/document.xml", b"<document />"),
        ("word/embeddings/payload.exe", b"MZpayload"),
    )

    with pytest.raises(UnsafeUploadError, match="可执行载荷"):
        validate_upload(
            "report.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content,
            max_uncompressed_bytes=1024,
        )


def test_upload_rejects_office_zip_bomb() -> None:
    content = _office_archive(
        ("[Content_Types].xml", b"<Types />"),
        ("xl/workbook.xml", b"0" * 5000),
    )

    with pytest.raises(UnsafeUploadError, match="超过大小限制"):
        validate_upload(
            "report.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content,
            max_uncompressed_bytes=1024,
        )
