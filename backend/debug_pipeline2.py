import sys

sys.path.insert(0, ".")

from transformers import pipeline

model_name = "uer/roberta-base-finetuned-dianping-chinese"

print("=== Testing with return_all_scores=False ===")
pipe = pipeline(
    "text-classification",
    model=model_name,
    tokenizer=model_name,
    device=-1,
    batch_size=2,
    return_all_scores=False,
)

texts = ["这家餐厅口味很好，服务态度也不错", "太难吃了，再也不来了"]
results = pipe(texts)
print(f"Results: {results}")
for i, r in enumerate(results):
    print(f"  [{i}] label={r.get('label')}, score={r.get('score')}")

print("\n=== Testing with return_all_scores=True ===")
pipe2 = pipeline(
    "text-classification",
    model=model_name,
    tokenizer=model_name,
    device=-1,
    batch_size=2,
    return_all_scores=True,
)

results2 = pipe2(texts)
print(f"Results type: {type(results2)}")
print(f"Results len: {len(results2)}")
for i, r in enumerate(results2):
    print(f"  [{i}] type={type(r)}, value={r}")
import sys
<<<<<<< HEAD

sys.path.insert(0, ".")

from transformers import pipeline
=======
sys.path.insert(0, '.')

from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)

model_name = "uer/roberta-base-finetuned-dianping-chinese"

print("=== Testing with return_all_scores=False ===")
pipe = pipeline(
    "text-classification",
    model=model_name,
    tokenizer=model_name,
    device=-1,
    batch_size=2,
    return_all_scores=False,
)

texts = ["这家餐厅口味很好，服务态度也不错", "太难吃了，再也不来了"]
results = pipe(texts)
print(f"Results: {results}")
for i, r in enumerate(results):
    print(f"  [{i}] label={r.get('label')}, score={r.get('score')}")

print("\n=== Testing with return_all_scores=True ===")
pipe2 = pipeline(
    "text-classification",
    model=model_name,
    tokenizer=model_name,
    device=-1,
    batch_size=2,
    return_all_scores=True,
)

results2 = pipe2(texts)
print(f"Results type: {type(results2)}")
print(f"Results len: {len(results2)}")
for i, r in enumerate(results2):
<<<<<<< HEAD
    print(f"  [{i}] type={type(r)}, value={r}")
=======
    print(f"  [{i}] type={type(r)}, value={r}")
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)
