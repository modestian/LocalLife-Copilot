import json
import logging
import os
from typing import Literal

import torch
from pydantic import BaseModel, field_validator
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

logger = logging.getLogger(__name__)

SENTIMENT_LABELS = ["NEGATIVE", "NEUTRAL", "POSITIVE"]
DEFAULT_BATCH_SIZE = 32

# 默认使用本地微调模型；若不存在则回退到 HuggingFace 远程模型
_LOCAL_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "training",
    "output",
    "final_model",
)
DEFAULT_MODEL_NAME = (
    _LOCAL_MODEL_DIR
    if os.path.isdir(_LOCAL_MODEL_DIR)
    else "uer/roberta-base-finetuned-dianping-chinese"
)


def _normalize_label(label) -> str:
    if isinstance(label, int):
        return SENTIMENT_LABELS[label]
    if isinstance(label, str):
        if label.isdigit():
            return SENTIMENT_LABELS[int(label)]
        label_upper = label.upper()
        if label_upper in SENTIMENT_LABELS:
            return label_upper
        label_map = {"NEG": "NEGATIVE", "NEUT": "NEUTRAL", "POS": "POSITIVE"}
        if label_upper in label_map:
            return label_map[label_upper]
        if "POSITIVE" in label_upper or "STAR 4" in label_upper or "STAR 5" in label_upper:
            return "POSITIVE"
        if "NEGATIVE" in label_upper or "STAR 1" in label_upper or "STAR 2" in label_upper:
            return "NEGATIVE"
        if "NEUTRAL" in label_upper or "STAR 3" in label_upper:
            return "NEUTRAL"
    return "NEUTRAL"


class SentimentResult(BaseModel):
    sentiment: Literal["POSITIVE", "NEUTRAL", "NEGATIVE"]
    confidence: float
    model_version: str
    aspect_labels: list[str] = []
    negative_reason: list[str] = []

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return round(value, 4)


class SentimentClassifier:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, batch_size: int = DEFAULT_BATCH_SIZE):
        self.model_name = model_name
        self.batch_size = batch_size
        self._pipeline = None
        self._model_version = None
        self._device = "cuda" if torch.cuda.is_available() else "cpu"

    @property
    def version(self) -> str:
        return self._model_version or "unknown"

    def load_model(self) -> None:
        model_path = os.path.abspath(self.model_name)
        logger.info(f"Loading sentiment model: {model_path} on {self._device}")
        self._pipeline = pipeline(
            "text-classification",
            model=model_path,
            tokenizer=model_path,
            device=0 if self._device == "cuda" else -1,
            batch_size=self.batch_size,
            return_all_scores=False,
        )
        self._model_version = f"{self.model_name}-{self._device}"
        logger.info(f"Model loaded successfully: {self._model_version}")

    def predict_single(self, text: str) -> SentimentResult:
        if not isinstance(text, str) or not text.strip():
            return SentimentResult(
                sentiment="NEUTRAL",
                confidence=0.0,
                model_version=self.version,
            )

        if self._pipeline is None:
            self.load_model()

        results = self._pipeline(text.strip())
        if isinstance(results, list) and len(results) > 0:
            result = results[0]
            if isinstance(result, list):
                max_score = max(result, key=lambda x: x["score"])
            else:
                max_score = result
        else:
            max_score = {"label": "NEUTRAL", "score": 0.0}

        label = max_score["label"]
        normalized_label = _normalize_label(label)

        return SentimentResult(
            sentiment=normalized_label,
            confidence=max_score["score"],
            model_version=self.version,
        )

    def predict_batch(self, texts: list[str]) -> list[SentimentResult]:
        if not texts:
            return []

        valid_texts = [
            (i, t.strip()) for i, t in enumerate(texts) if isinstance(t, str) and t.strip()
        ]
        invalid_indices = [i for i, t in enumerate(texts) if not (isinstance(t, str) and t.strip())]

        results = [None] * len(texts)
        if valid_texts:
            if self._pipeline is None:
                self.load_model()

            batch_texts = [t for _, t in valid_texts]
            batch_indices = [i for i, _ in valid_texts]

            pipeline_results = self._pipeline(batch_texts)
            for idx, result in zip(batch_indices, pipeline_results, strict=False):
                if isinstance(result, list):
                    max_score = max(result, key=lambda x: x["score"])
                else:
                    max_score = result

                label = max_score["label"]
                normalized_label = _normalize_label(label)
                results[idx] = SentimentResult(
                    sentiment=normalized_label,
                    confidence=max_score["score"],
                    model_version=self.version,
                )

        for idx in invalid_indices:
            results[idx] = SentimentResult(
                sentiment="NEUTRAL",
                confidence=0.0,
                model_version=self.version,
            )

        return results


class AspectExtractor:
    ASPECT_KEYWORDS = {
        "taste": ["口味", "味道", "好吃", "难吃", "美味", "口感", "香甜", "鲜美", "酸辣", "咸淡"],
        "portion": ["分量", "份量", "太少", "太多", "足量", "不足", "实在"],
        "price": ["价格", "便宜", "贵", "性价比", "实惠", "昂贵", "划算"],
        "freshness": ["新鲜", "不新鲜", "变质", "发霉", "过期"],
        "appearance": ["颜值", "好看", "漂亮", "卖相", "精致", "难看"],
        "variety": ["种类", "品种", "选择", "多样", "单一", "丰富"],
        "space": ["空间", "大小", "宽敞", "狭窄", "拥挤"],
        "quiet": ["安静", "嘈杂", "吵闹", "喧哗", "清静"],
        "decoration": ["装修", "环境", "氛围", "风格", "设计", "特色"],
        "hygiene": ["干净", "卫生", "脏", "清洁", "整洁"],
        "location": ["位置", "交通", "方便", "好找", "偏僻"],
        "seating": ["座位", "座位", "坐", "拥挤"],
        "waiting_time": ["等待", "等", "慢", "快", "久", "迅速"],
        "attitude": ["态度", "热情", "冷漠", "耐心", "服务"],
        "efficiency": ["效率", "速度", "快", "慢", "麻利"],
        "parking": ["停车", "车位", "方便", "困难"],
        "packing": ["打包", "包装", "漏", "密封"],
        "discount": ["优惠", "团购", "折扣", "活动"],
        "set_meal": ["套餐", "组合", "搭配"],
        "equipment": ["设备", "设施", "WiFi", "空调"],
        "overall": ["整体", "综合", "体验", "感觉", "推荐"],
    }

    NEGATIVE_REASON_KEYWORDS = {
        "taste_bad": ["难吃", "难以下咽", "恶心"],
        "taste_unbalanced": ["太咸", "太淡", "太辣", "没味道"],
        "cold_food": ["凉了", "冷了", "冰凉"],
        "too_small": ["太少", "不够", "分量不足"],
        "stale": ["不新鲜", "放久了"],
        "spoiled": ["变质", "发霉", "发酸"],
        "overpriced": ["太贵", "不值", "性价比低"],
        "false_discount": ["虚假", "欺骗", "套路"],
        "dirty": ["脏", "不干净", "油污"],
        "loud": ["吵", "嘈杂", "声音大"],
        "no_seat": ["没座位", "没位置"],
        "slow_wait": ["等太久", "上菜慢"],
        "rude_staff": ["态度差", "冷漠", "不耐烦"],
        "wrong_order": ["上错", "漏单"],
        "no_parking": ["没车位", "停车难"],
        "bad_pack": ["漏", "破", "洒"],
        "equipment_broken": ["坏了", "失效"],
        "close_early": ["提前打烊", "赶客"],
        "delivery_delay": ["超时", "迟到"],
    }

    @classmethod
    def extract_aspects(cls, text: str) -> list[str]:
        if not isinstance(text, str):
            return []
        aspects = []
        for aspect, keywords in cls.ASPECT_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                aspects.append(aspect)
        return sorted(aspects)

    @classmethod
    def extract_negative_reasons(cls, text: str) -> list[str]:
        if not isinstance(text, str):
            return []
        reasons = []
        for reason, keywords in cls.NEGATIVE_REASON_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                reasons.append(reason)
        return sorted(reasons)


class SentimentAnalyzer:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, batch_size: int = DEFAULT_BATCH_SIZE):
        self.classifier = SentimentClassifier(model_name, batch_size)
        self.aspect_extractor = AspectExtractor()

    @property
    def version(self) -> str:
        return self.classifier.version

    def analyze_single(self, text: str) -> SentimentResult:
        result = self.classifier.predict_single(text)
        result.aspect_labels = self.aspect_extractor.extract_aspects(text)
        if result.sentiment == "NEGATIVE":
            result.negative_reason = self.aspect_extractor.extract_negative_reasons(text)
        return result

    def analyze_batch(self, texts: list[str]) -> list[SentimentResult]:
        results = self.classifier.predict_batch(texts)
        for _i, (text, result) in enumerate(zip(texts, results, strict=False)):
            result.aspect_labels = self.aspect_extractor.extract_aspects(text)
            if result.sentiment == "NEGATIVE":
                result.negative_reason = self.aspect_extractor.extract_negative_reasons(text)
        return results
<<<<<<< HEAD
=======
import json
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)
import logging
import os
from typing import Literal

import torch
from pydantic import BaseModel, field_validator
<<<<<<< HEAD
from transformers import pipeline
=======
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)

logger = logging.getLogger(__name__)

SENTIMENT_LABELS = ["NEGATIVE", "NEUTRAL", "POSITIVE"]
<<<<<<< HEAD
DEFAULT_BATCH_SIZE = 32

# 默认使用本地微调模型；若不存在则回退到 HuggingFace 远程模型
_LOCAL_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "training",
    "output",
    "final_model",
)
DEFAULT_MODEL_NAME = (
    _LOCAL_MODEL_DIR
    if os.path.isdir(_LOCAL_MODEL_DIR)
    else "uer/roberta-base-finetuned-dianping-chinese"
)

=======
DEFAULT_MODEL_NAME = "training/output/final_model"
DEFAULT_BATCH_SIZE = 32

>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)

def _normalize_label(label) -> str:
    if isinstance(label, int):
        return SENTIMENT_LABELS[label]
    if isinstance(label, str):
        if label.isdigit():
            return SENTIMENT_LABELS[int(label)]
        label_upper = label.upper()
        if label_upper in SENTIMENT_LABELS:
            return label_upper
        label_map = {"NEG": "NEGATIVE", "NEUT": "NEUTRAL", "POS": "POSITIVE"}
        if label_upper in label_map:
            return label_map[label_upper]
        if "POSITIVE" in label_upper or "STAR 4" in label_upper or "STAR 5" in label_upper:
            return "POSITIVE"
        if "NEGATIVE" in label_upper or "STAR 1" in label_upper or "STAR 2" in label_upper:
            return "NEGATIVE"
        if "NEUTRAL" in label_upper or "STAR 3" in label_upper:
            return "NEUTRAL"
    return "NEUTRAL"


class SentimentResult(BaseModel):
    sentiment: Literal["POSITIVE", "NEUTRAL", "NEGATIVE"]
    confidence: float
    model_version: str
    aspect_labels: list[str] = []
    negative_reason: list[str] = []

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return round(value, 4)


class SentimentClassifier:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, batch_size: int = DEFAULT_BATCH_SIZE):
        self.model_name = model_name
        self.batch_size = batch_size
        self._pipeline = None
        self._model_version = None
        self._device = "cuda" if torch.cuda.is_available() else "cpu"

    @property
    def version(self) -> str:
        return self._model_version or "unknown"

    def load_model(self) -> None:
<<<<<<< HEAD
        logger.info(f"Loading sentiment model: {self.model_name} on {self._device}")
        self._pipeline = pipeline(
            "text-classification",
            model=self.model_name,
            tokenizer=self.model_name,
=======
        model_path = os.path.abspath(self.model_name)
        logger.info(f"Loading sentiment model: {model_path} on {self._device}")
        self._pipeline = pipeline(
            "text-classification",
            model=model_path,
            tokenizer=model_path,
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)
            device=0 if self._device == "cuda" else -1,
            batch_size=self.batch_size,
            return_all_scores=False,
        )
        self._model_version = f"{self.model_name}-{self._device}"
        logger.info(f"Model loaded successfully: {self._model_version}")

    def predict_single(self, text: str) -> SentimentResult:
        if not isinstance(text, str) or not text.strip():
            return SentimentResult(
                sentiment="NEUTRAL",
                confidence=0.0,
                model_version=self.version,
            )

        if self._pipeline is None:
            self.load_model()

        results = self._pipeline(text.strip())
        if isinstance(results, list) and len(results) > 0:
            result = results[0]
            if isinstance(result, list):
                max_score = max(result, key=lambda x: x["score"])
            else:
                max_score = result
        else:
            max_score = {"label": "NEUTRAL", "score": 0.0}

        label = max_score["label"]
        normalized_label = _normalize_label(label)

        return SentimentResult(
            sentiment=normalized_label,
            confidence=max_score["score"],
            model_version=self.version,
        )

    def predict_batch(self, texts: list[str]) -> list[SentimentResult]:
        if not texts:
            return []

<<<<<<< HEAD
        valid_texts = [
            (i, t.strip()) for i, t in enumerate(texts) if isinstance(t, str) and t.strip()
        ]
=======
        valid_texts = [(i, t.strip()) for i, t in enumerate(texts) if isinstance(t, str) and t.strip()]
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)
        invalid_indices = [i for i, t in enumerate(texts) if not (isinstance(t, str) and t.strip())]

        results = [None] * len(texts)
        if valid_texts:
            if self._pipeline is None:
                self.load_model()

            batch_texts = [t for _, t in valid_texts]
            batch_indices = [i for i, _ in valid_texts]

            pipeline_results = self._pipeline(batch_texts)
<<<<<<< HEAD
            for idx, result in zip(batch_indices, pipeline_results, strict=False):
=======
            for idx, result in zip(batch_indices, pipeline_results):
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)
                if isinstance(result, list):
                    max_score = max(result, key=lambda x: x["score"])
                else:
                    max_score = result

                label = max_score["label"]
                normalized_label = _normalize_label(label)
                results[idx] = SentimentResult(
                    sentiment=normalized_label,
                    confidence=max_score["score"],
                    model_version=self.version,
                )

        for idx in invalid_indices:
            results[idx] = SentimentResult(
                sentiment="NEUTRAL",
                confidence=0.0,
                model_version=self.version,
            )

        return results


class AspectExtractor:
    ASPECT_KEYWORDS = {
        "taste": ["口味", "味道", "好吃", "难吃", "美味", "口感", "香甜", "鲜美", "酸辣", "咸淡"],
        "portion": ["分量", "份量", "太少", "太多", "足量", "不足", "实在"],
        "price": ["价格", "便宜", "贵", "性价比", "实惠", "昂贵", "划算"],
        "freshness": ["新鲜", "不新鲜", "变质", "发霉", "过期"],
        "appearance": ["颜值", "好看", "漂亮", "卖相", "精致", "难看"],
        "variety": ["种类", "品种", "选择", "多样", "单一", "丰富"],
        "space": ["空间", "大小", "宽敞", "狭窄", "拥挤"],
        "quiet": ["安静", "嘈杂", "吵闹", "喧哗", "清静"],
        "decoration": ["装修", "环境", "氛围", "风格", "设计", "特色"],
        "hygiene": ["干净", "卫生", "脏", "清洁", "整洁"],
        "location": ["位置", "交通", "方便", "好找", "偏僻"],
        "seating": ["座位", "座位", "坐", "拥挤"],
        "waiting_time": ["等待", "等", "慢", "快", "久", "迅速"],
        "attitude": ["态度", "热情", "冷漠", "耐心", "服务"],
        "efficiency": ["效率", "速度", "快", "慢", "麻利"],
        "parking": ["停车", "车位", "方便", "困难"],
        "packing": ["打包", "包装", "漏", "密封"],
        "discount": ["优惠", "团购", "折扣", "活动"],
        "set_meal": ["套餐", "组合", "搭配"],
        "equipment": ["设备", "设施", "WiFi", "空调"],
        "overall": ["整体", "综合", "体验", "感觉", "推荐"],
    }

    NEGATIVE_REASON_KEYWORDS = {
        "taste_bad": ["难吃", "难以下咽", "恶心"],
        "taste_unbalanced": ["太咸", "太淡", "太辣", "没味道"],
        "cold_food": ["凉了", "冷了", "冰凉"],
        "too_small": ["太少", "不够", "分量不足"],
        "stale": ["不新鲜", "放久了"],
        "spoiled": ["变质", "发霉", "发酸"],
        "overpriced": ["太贵", "不值", "性价比低"],
        "false_discount": ["虚假", "欺骗", "套路"],
        "dirty": ["脏", "不干净", "油污"],
        "loud": ["吵", "嘈杂", "声音大"],
        "no_seat": ["没座位", "没位置"],
        "slow_wait": ["等太久", "上菜慢"],
        "rude_staff": ["态度差", "冷漠", "不耐烦"],
        "wrong_order": ["上错", "漏单"],
        "no_parking": ["没车位", "停车难"],
        "bad_pack": ["漏", "破", "洒"],
        "equipment_broken": ["坏了", "失效"],
        "close_early": ["提前打烊", "赶客"],
        "delivery_delay": ["超时", "迟到"],
    }

    @classmethod
    def extract_aspects(cls, text: str) -> list[str]:
        if not isinstance(text, str):
            return []
        aspects = []
        for aspect, keywords in cls.ASPECT_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                aspects.append(aspect)
        return sorted(aspects)

    @classmethod
    def extract_negative_reasons(cls, text: str) -> list[str]:
        if not isinstance(text, str):
            return []
        reasons = []
        for reason, keywords in cls.NEGATIVE_REASON_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                reasons.append(reason)
        return sorted(reasons)


class SentimentAnalyzer:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, batch_size: int = DEFAULT_BATCH_SIZE):
        self.classifier = SentimentClassifier(model_name, batch_size)
        self.aspect_extractor = AspectExtractor()

    @property
    def version(self) -> str:
        return self.classifier.version

    def analyze_single(self, text: str) -> SentimentResult:
        result = self.classifier.predict_single(text)
        result.aspect_labels = self.aspect_extractor.extract_aspects(text)
        if result.sentiment == "NEGATIVE":
            result.negative_reason = self.aspect_extractor.extract_negative_reasons(text)
        return result

    def analyze_batch(self, texts: list[str]) -> list[SentimentResult]:
        results = self.classifier.predict_batch(texts)
<<<<<<< HEAD
        for _i, (text, result) in enumerate(zip(texts, results, strict=False)):
            result.aspect_labels = self.aspect_extractor.extract_aspects(text)
            if result.sentiment == "NEGATIVE":
                result.negative_reason = self.aspect_extractor.extract_negative_reasons(text)
        return results
=======
        for i, (text, result) in enumerate(zip(texts, results)):
            result.aspect_labels = self.aspect_extractor.extract_aspects(text)
            if result.sentiment == "NEGATIVE":
                result.negative_reason = self.aspect_extractor.extract_negative_reasons(text)
        return results
>>>>>>> 2ae14b5 (feat:TK-401-04 特征与归因提取、结果持久化  TK-401-06 离线模型评测)
