"""Knowledge ingestion records, ports, and file loader adapters."""

from app.etl.dataframe import CANONICAL_COLUMNS, records_to_dataframe
from app.etl.loaders import (
    CsvLoader,
    DocxLoader,
    FileLoader,
    FileLoadError,
    MarkdownLoader,
    PdfLoader,
    TextLoader,
    XlsxLoader,
    loader_for,
    normalized_content_hash,
)
from app.etl.models import ChunkRecord, CleanStatus, DocumentRecord, JsonValue, Metadata
from app.etl.ports import Cleaner, Loader, Splitter

__all__ = [
    "CANONICAL_COLUMNS",
    "ChunkRecord",
    "Cleaner",
    "CleanStatus",
    "CsvLoader",
    "DocxLoader",
    "DocumentRecord",
    "FileLoadError",
    "FileLoader",
    "JsonValue",
    "Loader",
    "MarkdownLoader",
    "Metadata",
    "PdfLoader",
    "Splitter",
    "TextLoader",
    "XlsxLoader",
    "loader_for",
    "normalized_content_hash",
    "records_to_dataframe",
]
