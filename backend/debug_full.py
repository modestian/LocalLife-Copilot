import sys

sys.path.insert(0, ".")

from app.analytics import SentimentAnalyzer

analyzer = SentimentAnalyzer()

texts = ["这家餐厅口味很好，服务态度也不错", "太难吃了，再也不来了"]

print("=== Testing analyze_batch ===")
results = analyzer.analyze_batch(texts)

for i, (text, result) in enumerate(zip(texts, results, strict=False)):
    print(f"\nText {i}: {text}")
    print(f"  sentiment: {result.sentiment}")
    print(f"  confidence: {result.confidence}")
    print(f"  aspect_labels: {result.aspect_labels}")
    print(f"  negative_reason: {result.negative_reason}")

print("\n=== Testing analyze_single ===")
result1 = analyzer.analyze_single(texts[0])
print(f"Text 0: {texts[0]}")
print(f"  sentiment: {result1.sentiment}")
print(f"  confidence: {result1.confidence}")
print(f"  aspect_labels: {result1.aspect_labels}")
print(f"  negative_reason: {result1.negative_reason}")

result2 = analyzer.analyze_single(texts[1])
print(f"\nText 1: {texts[1]}")
print(f"  sentiment: {result2.sentiment}")
print(f"  confidence: {result2.confidence}")
print(f"  aspect_labels: {result2.aspect_labels}")
print(f"  negative_reason: {result2.negative_reason}")
import sys
<<<<<<< HEAD

sys.path.insert(0, ".")
=======
sys.path.insert(0, '.')
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)

from app.analytics import SentimentAnalyzer

analyzer = SentimentAnalyzer()

texts = ["这家餐厅口味很好，服务态度也不错", "太难吃了，再也不来了"]

print("=== Testing analyze_batch ===")
results = analyzer.analyze_batch(texts)

<<<<<<< HEAD
for i, (text, result) in enumerate(zip(texts, results, strict=False)):
=======
for i, (text, result) in enumerate(zip(texts, results)):
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)
    print(f"\nText {i}: {text}")
    print(f"  sentiment: {result.sentiment}")
    print(f"  confidence: {result.confidence}")
    print(f"  aspect_labels: {result.aspect_labels}")
    print(f"  negative_reason: {result.negative_reason}")

print("\n=== Testing analyze_single ===")
result1 = analyzer.analyze_single(texts[0])
print(f"Text 0: {texts[0]}")
print(f"  sentiment: {result1.sentiment}")
print(f"  confidence: {result1.confidence}")
print(f"  aspect_labels: {result1.aspect_labels}")
print(f"  negative_reason: {result1.negative_reason}")

result2 = analyzer.analyze_single(texts[1])
print(f"\nText 1: {texts[1]}")
print(f"  sentiment: {result2.sentiment}")
print(f"  confidence: {result2.confidence}")
print(f"  aspect_labels: {result2.aspect_labels}")
<<<<<<< HEAD
print(f"  negative_reason: {result2.negative_reason}")
=======
print(f"  negative_reason: {result2.negative_reason}")
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)
