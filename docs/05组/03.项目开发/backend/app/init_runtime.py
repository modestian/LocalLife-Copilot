from opensearchpy import OpenSearch

from app.core.config import get_settings
from app.infrastructure.search.indexes import ensure_chunk_index


def main() -> None:
    """Create the development search index once; safe to run repeatedly."""
    settings = get_settings()
    client = OpenSearch(settings.opensearch_url)
    try:
        ensure_chunk_index(
            client,
            index=settings.opensearch_concrete_index,
            read_alias=settings.opensearch_read_alias,
            write_alias=settings.opensearch_write_alias,
            embedding_dimension=settings.embedding_dimension,
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
