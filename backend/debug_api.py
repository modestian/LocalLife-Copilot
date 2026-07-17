import sys

sys.path.insert(0, ".")

from app.analytics import AspectExtractor, SentimentAnalyzer, SentimentClassifier

print("=== Testing with same texts as API ===")
texts = ["这家餐厅口味很好，服务态度也不错", "太难吃了，再也不来了"]

print("\n1. Direct pipeline test:")
from transformers import pipeline

pipe = pipeline(
    "text-classification",
    model="uer/roberta-base-finetuned-dianping-chinese",
    tokenizer="uer/roberta-base-finetuned-dianping-chinese",
    device=-1,
    batch_size=2,
    return_all_scores=False,
)
results = pipe(texts)
for i, r in enumerate(results):
    print(f"  Text {i}: label={r['label']}, score={r['score']}")

print("\n2. SentimentClassifier test:")
classifier = SentimentClassifier()
classifier_results = classifier.predict_batch(texts)
for i, r in enumerate(classifier_results):
    print(f"  Text {i}: sentiment={r.sentiment}, confidence={r.confidence}")

print("\n3. AspectExtractor test:")
for i, text in enumerate(texts):
    aspects = AspectExtractor.extract_aspects(text)
    reasons = AspectExtractor.extract_negative_reasons(text)
    print(f"  Text {i}: aspects={aspects}, reasons={reasons}")

print("\n4. Full SentimentAnalyzer test:")
analyzer = SentimentAnalyzer()
analyzer_results = analyzer.analyze_batch(texts)
for i, r in enumerate(analyzer_results):
    print(
        f"  Text {i}: sentiment={r.sentiment}, confidence={r.confidence}, aspects={r.aspect_labels}, reasons={r.negative_reason}"
    )

print("\n5. Check label normalization:")
test_labels = ["positive (stars 4 and 5)", "negative (stars 1, 2 and 3)"]
from app.analytics.sentiment_classifier import _normalize_label

for label in test_labels:
    print(f"  '{label}' -> '{_normalize_label(label)}'")
