import sys
import traceback

sys.path.insert(0, ".")

from transformers import pipeline

model_name = "uer/roberta-base-finetuned-dianping-chinese"

print(f"Loading model: {model_name}")
pipe = pipeline(
    "text-classification",
    model=model_name,
    tokenizer=model_name,
    device=-1,
    batch_size=2,
    return_all_scores=True,
)

print("\nTesting single text...")
try:
    result = pipe("这家餐厅很好吃")
    print(f"Raw result type: {type(result)}")
    print(f"Raw result: {result}")
    if result:
        print(f"First element type: {type(result[0])}")
        print(f"First element: {result[0]}")
        if isinstance(result[0], list):
            for i, item in enumerate(result[0]):
                print(f"  [{i}] type={type(item)}, value={item}")
                if isinstance(item, dict):
                    print(f"    keys: {list(item.keys())}")
except Exception as e:
    print(f"Error: {e}")
    traceback.print_exc()

print("\nTesting batch...")
try:
    results = pipe(["这家餐厅很好吃", "太难吃了"])
    print(f"Batch result type: {type(results)}")
    print(f"Batch result len: {len(results)}")
    for i, r in enumerate(results):
        print(f"\nResult {i}:")
        print(f"  type: {type(r)}")
        print(f"  value: {r}")
        if isinstance(r, list):
            for j, item in enumerate(r):
                print(f"    [{j}] type={type(item)}, value={item}")
                if isinstance(item, dict):
                    print(f"      keys: {list(item.keys())}")
except Exception as e:
    print(f"Error: {e}")
    traceback.print_exc()
import sys
import traceback

sys.path.insert(0, ".")

from transformers import pipeline

model_name = "uer/roberta-base-finetuned-dianping-chinese"

print(f"Loading model: {model_name}")
pipe = pipeline(
    "text-classification",
    model=model_name,
    tokenizer=model_name,
    device=-1,
    batch_size=2,
    return_all_scores=True,
)

print("\nTesting single text...")
try:
    result = pipe("这家餐厅很好吃")
    print(f"Raw result type: {type(result)}")
    print(f"Raw result: {result}")
    if result:
        print(f"First element type: {type(result[0])}")
        print(f"First element: {result[0]}")
        if isinstance(result[0], list):
            for i, item in enumerate(result[0]):
                print(f"  [{i}] type={type(item)}, value={item}")
                if isinstance(item, dict):
                    print(f"    keys: {list(item.keys())}")
except Exception as e:
    print(f"Error: {e}")
    traceback.print_exc()

print("\nTesting batch...")
try:
    results = pipe(["这家餐厅很好吃", "太难吃了"])
    print(f"Batch result type: {type(results)}")
    print(f"Batch result len: {len(results)}")
    for i, r in enumerate(results):
        print(f"\nResult {i}:")
        print(f"  type: {type(r)}")
        print(f"  value: {r}")
        if isinstance(r, list):
            for j, item in enumerate(r):
                print(f"    [{j}] type={type(item)}, value={item}")
                if isinstance(item, dict):
                    print(f"      keys: {list(item.keys())}")
except Exception as e:
    print(f"Error: {e}")
<<<<<<< HEAD
    traceback.print_exc()
=======
    traceback.print_exc()
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)
