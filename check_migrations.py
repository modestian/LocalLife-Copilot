import re
files = [
    'backend/migrations/versions/20260717_0003_knowledge_metadata.py',
    'backend/migrations/versions/20260717_0003_sentiment_analysis.py',
    'backend/migrations/versions/20260717_0004_sentiment_analysis.py',
]
for f in files:
    with open(f, encoding='utf-8') as fh:
        c = fh.read()
    rev = re.search(r'revision:\s*str\s*=\s*["\'](.+?)["\']', c)
    down = re.search(r'down_revision:\s*str\s*\|\s*None\s*=\s*["\'](.+?)["\']', c)
    print(f'{f}:')
    print(f'  revision = {rev.group(1) if rev else "?"}')
    print(f'  down_revision = {down.group(1) if down else "None"}')
