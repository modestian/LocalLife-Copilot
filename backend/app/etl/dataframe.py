from collections.abc import Iterable

import pandas as pd

from app.etl.models import DocumentRecord

CANONICAL_COLUMNS = ("content", "metadata", "source_key", "content_hash", "clean_status")


def records_to_dataframe(records: Iterable[DocumentRecord]) -> pd.DataFrame:
    """Materialize document records using the canonical ETL DataFrame schema."""
    rows = [
        {
            "content": record.content,
            "metadata": record.metadata,
            "source_key": record.source_key,
            "content_hash": record.content_hash,
            "clean_status": record.clean_status.value,
        }
        for record in records
    ]
    frame = pd.DataFrame.from_records(rows, columns=CANONICAL_COLUMNS)
    for column in ("content", "source_key", "content_hash", "clean_status"):
        frame[column] = frame[column].astype("string")
    return frame
