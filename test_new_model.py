from transformers import pipeline
from app.analytics import AspectExtractor

# 加载训练好的三分类模型
classifier = pipeline(
    "text-classification",
    model="backend/training/output/final_model",
    tokenizer="backend/training/output/final_model",
    device=-1,
    return_all_scores=True,
)

test_texts = [
    "这家餐厅口味很好，服务态度也不错",
    "太难吃了，再也不来了",
    "还行吧，一般般",
]

results = classifier(test_texts)
for text, result in zip(test_texts, results):
    print(f"\nText: {text}")
    for r in result:
        print(f"  {r['label']}: {r['score']:.4f}")
    aspects = AspectExtractor.extract_aspects(text)
    print(f"  Aspects: {aspects}")
