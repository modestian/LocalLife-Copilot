from opensearchpy import OpenSearch

from app.core.config import get_settings


def main() -> None:
    """Create the development search index once; safe to run repeatedly."""
    settings = get_settings()
    client = OpenSearch(settings.opensearch_url)
    try:
        if client.indices.exists(index=settings.opensearch_index):
            return
        client.indices.create(
            index=settings.opensearch_index,
            body={
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "properties": {
                        "content": {"type": "text"},
                        "source_key": {"type": "keyword"},
                        "updated_at": {"type": "date"},
                    }
                },
            },
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
