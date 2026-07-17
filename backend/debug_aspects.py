import sys

sys.path.insert(0, ".")

from app.analytics import AspectExtractor

text1 = "这家餐厅口味很好，服务态度也不错"
text2 = "太难吃了，再也不来了"

print("=== Text 1:", text1, "===")
print("Aspect keywords to match:")
for aspect, keywords in AspectExtractor.ASPECT_KEYWORDS.items():
    matched = [kw for kw in keywords if kw in text1]
    if matched:
        print(f"  {aspect}: {matched}")

print("\n=== Text 2:", text2, "===")
print("Aspect keywords to match:")
for aspect, keywords in AspectExtractor.ASPECT_KEYWORDS.items():
    matched = [kw for kw in keywords if kw in text2]
    if matched:
        print(f"  {aspect}: {matched}")

print("\nNegative reason keywords to match:")
for reason, keywords in AspectExtractor.NEGATIVE_REASON_KEYWORDS.items():
    matched = [kw for kw in keywords if kw in text2]
    if matched:
        print(f"  {reason}: {matched}")

print("\n=== Extraction Results ===")
print("text1 aspects:", AspectExtractor.extract_aspects(text1))
print("text2 aspects:", AspectExtractor.extract_aspects(text2))
print("text2 reasons:", AspectExtractor.extract_negative_reasons(text2))
import sys
<<<<<<< HEAD

sys.path.insert(0, ".")
=======
sys.path.insert(0, '.')
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)

from app.analytics import AspectExtractor

text1 = "这家餐厅口味很好，服务态度也不错"
text2 = "太难吃了，再也不来了"

print("=== Text 1:", text1, "===")
print("Aspect keywords to match:")
for aspect, keywords in AspectExtractor.ASPECT_KEYWORDS.items():
    matched = [kw for kw in keywords if kw in text1]
    if matched:
        print(f"  {aspect}: {matched}")

print("\n=== Text 2:", text2, "===")
print("Aspect keywords to match:")
for aspect, keywords in AspectExtractor.ASPECT_KEYWORDS.items():
    matched = [kw for kw in keywords if kw in text2]
    if matched:
        print(f"  {aspect}: {matched}")

print("\nNegative reason keywords to match:")
for reason, keywords in AspectExtractor.NEGATIVE_REASON_KEYWORDS.items():
    matched = [kw for kw in keywords if kw in text2]
    if matched:
        print(f"  {reason}: {matched}")

print("\n=== Extraction Results ===")
print("text1 aspects:", AspectExtractor.extract_aspects(text1))
print("text2 aspects:", AspectExtractor.extract_aspects(text2))
<<<<<<< HEAD
print("text2 reasons:", AspectExtractor.extract_negative_reasons(text2))
=======
print("text2 reasons:", AspectExtractor.extract_negative_reasons(text2))
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)
