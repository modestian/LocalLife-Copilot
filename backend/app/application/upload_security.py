import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    filename: str
    safe_filename: str
    mime_type: str


class UnsafeUploadError(ValueError):
    pass


_ALLOWED_MIME_TYPES = {
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".csv": {"text/csv", "application/csv", "text/plain"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}
_EXECUTABLE_SUFFIXES = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".jar",
    ".js",
    ".ps1",
    ".scr",
    ".sh",
    ".vbs",
}


def validate_upload(
    filename: str | None,
    content_type: str | None,
    content: bytes,
    *,
    max_uncompressed_bytes: int,
) -> ValidatedUpload:
    raw_name = (filename or "").strip()
    normalized_path = raw_name.replace("\\", "/")
    path = PurePosixPath(normalized_path)
    if not raw_name or path.is_absolute() or ".." in path.parts or path.name != normalized_path:
        raise UnsafeUploadError("文件名包含不安全路径")

    suffix = path.suffix.casefold()
    if suffix not in _ALLOWED_MIME_TYPES:
        raise UnsafeUploadError("不支持该文件扩展名")
    mime_type = (content_type or "").split(";", 1)[0].strip().casefold()
    if mime_type not in _ALLOWED_MIME_TYPES[suffix]:
        raise UnsafeUploadError("文件 MIME 类型与扩展名不匹配")
    if content.startswith((b"MZ", b"\x7fELF", b"#!")):
        raise UnsafeUploadError("检测到可执行文件内容")

    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise UnsafeUploadError("PDF 文件签名无效")
    if suffix in {".txt", ".md", ".csv"} and b"\x00" in content[:8192]:
        raise UnsafeUploadError("文本文件包含二进制内容")
    if suffix in {".docx", ".xlsx"}:
        _validate_office_archive(content, suffix, max_uncompressed_bytes)

    safe_name = re.sub(r"[^0-9A-Za-z._-]", "_", path.name)[:200]
    return ValidatedUpload(path.name, safe_name, mime_type)


def _validate_office_archive(content: bytes, suffix: str, max_uncompressed_bytes: int) -> None:
    required_entry = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if "[Content_Types].xml" not in names or required_entry not in names:
                raise UnsafeUploadError("Office 文件结构无效")
            if len(entries) > 2000:
                raise UnsafeUploadError("Office 压缩包条目过多")

            total_compressed = 0
            total_uncompressed = 0
            for entry in entries:
                entry_path = PurePosixPath(entry.filename.replace("\\", "/"))
                if entry_path.is_absolute() or ".." in entry_path.parts:
                    raise UnsafeUploadError("Office 压缩包包含路径穿越条目")
                if entry.flag_bits & 0x1:
                    raise UnsafeUploadError("不接受加密 Office 压缩包")
                if entry_path.suffix.casefold() in _EXECUTABLE_SUFFIXES:
                    raise UnsafeUploadError("Office 文件包含可执行载荷")
                if entry_path.name.casefold() == "vbaproject.bin":
                    raise UnsafeUploadError("Office 文件包含宏载荷")
                total_compressed += entry.compress_size
                total_uncompressed += entry.file_size

            if total_uncompressed > max_uncompressed_bytes:
                raise UnsafeUploadError("Office 文件解压后超过大小限制")
            if total_compressed and total_uncompressed > total_compressed * 100:
                raise UnsafeUploadError("检测到高压缩比 Office 文件")
    except zipfile.BadZipFile as exc:
        raise UnsafeUploadError("Office 文件签名无效") from exc
