import logging
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

SENTIMENT_LABELS = ["NEGATIVE", "NEUTRAL", "POSITIVE"]
DEFAULT_BATCH_SIZE = 32

# Patterns that indicate an objective, factual description (not sentiment).
# If any of these appear AND no strong sentiment word is present, the text is
# classified as NEUTRAL regardless of model confidence.
_FACTUAL_PATTERN = re.compile(
    r"营业时间|正常营业|均价|位于[^好]|出站步行|可达|"
    r"提供免费WiFi|密码张贴|全天可用|无需额外|"
    r"支持堂食|消费方式|暂不支持|电话预约|"
    r"分为|两小时内免费|额外收取|共\d+[个款种]|"
    r"中等|标准|持平|适中|无惊喜|无功无过"
)

# Strong sentiment words that signal an opinion rather than a fact.
# Their presence blocks factual-neutral detection.
_SENTIMENT_BLOCKERS = {
    # Positive
    "好吃",
    "美味",
    "满足",
    "推荐",
    "正宗",
    "鲜嫩",
    "浓郁",
    "清爽",
    "宽敞",
    "热情",
    "耐心",
    "严实",
    "流畅",
    "准时",
    "用心",
    "首选",
    "满分",
    "拉满",
    "极佳",
    "超出预期",
    "宝藏",
    "无短板",
    "适配",
    "出片",
    # Negative
    "难吃",
    "难以下咽",
    "变质",
    "发霉",
    "缩水",
    "踩雷",
    "干柴",
    "发酸",
    "油污",
    "嘈杂",
    "吵闹",
    "恶劣",
    "不耐烦",
    "破损",
    "失效",
    "损坏",
    "闷热",
    "赶客",
    "虚高",
    "冰冷",
    "发苦",
    "失衡",
    "堆积",
}

# 默认使用本地微调模型；若不存在则回退到 HuggingFace 远程模型
# Model artifacts are delivered separately from Git.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_LOCAL_MODEL_DIR = _BACKEND_DIR / "training" / "output" / "final_model"
DEFAULT_MODEL_NAME = (
    os.getenv("SENTIMENT_MODEL")
    or (str(_LOCAL_MODEL_DIR) if _LOCAL_MODEL_DIR.is_dir() else None)
    or "uer/roberta-base-finetuned-dianping-chinese"
)
DEFAULT_MODEL_REVISION = os.getenv("SENTIMENT_MODEL_REVISION") or None


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
    aspect_labels: list[str] = Field(default_factory=list)
    negative_reason: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return round(value, 4)


class SentimentClassifier:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        batch_size: int = DEFAULT_BATCH_SIZE,
        revision: str | None = DEFAULT_MODEL_REVISION,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self.revision = revision
        self._pipeline = None
        self._model_version = None
        self._device = None
        self._neutral_margin_threshold = float(os.getenv("SENTIMENT_NEUTRAL_MARGIN", "0.25"))

    @property
    def version(self) -> str:
        return self._model_version or "unknown"

    def load_model(self) -> None:
        import torch
        from transformers import pipeline

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        model_ref = self._resolve_model_reference()
        logger.info("Loading sentiment model: %s on %s", model_ref, self._device)
        model_kwargs = {"revision": self.revision} if self.revision else {}
        self._pipeline = pipeline(
            "text-classification",
            model=model_ref,
            tokenizer=model_ref,
            device=0 if self._device == "cuda" else -1,
            batch_size=self.batch_size,
            top_k=None,
            **model_kwargs,
        )
        configured_labels = {
            _normalize_label(label) for label in self._pipeline.model.config.id2label.values()
        }
        if configured_labels != set(SENTIMENT_LABELS):
            raise RuntimeError(
                "Configured sentiment model is not a NEGATIVE/NEUTRAL/POSITIVE classifier: "
                f"{sorted(configured_labels)}"
            )
        revision = self.revision or "unversioned"
        self._model_version = f"{self.model_name}@{revision}"
        logger.info("Model loaded successfully: %s", self._model_version)

    def _resolve_model_reference(self) -> str:
        """Keep Hub IDs intact while resolving an existing local artifact path."""
        candidate = Path(self.model_name).expanduser()
        if candidate.exists():
            return str(candidate.resolve())
        if candidate.is_absolute() or self.model_name.startswith((".", "~")):
            raise FileNotFoundError(
                f"Sentiment model directory does not exist: {candidate}. "
                "See backend/training/README.md."
            )
        return self.model_name

    def _is_factual_neutral(self, text: str) -> bool:
        """Detect objective, factual descriptions (hours, prices, locations, etc.).

        Such texts contain no sentiment and should always be NEUTRAL,
        regardless of model confidence.
        """
        if not text or not _FACTUAL_PATTERN.search(text):
            return False
        for word in _SENTIMENT_BLOCKERS:
            if word in text:
                return False
        logger.debug("Factual neutral detected: %s", text[:50])
        return True

    def _calibrate_neutral(self, scores: list[dict], text: str = "") -> tuple[str, float]:
        """Apply margin-based neutral calibration.

        If top-1 is POSITIVE/NEGATIVE but NEUTRAL score is close
        (margin < _neutral_margin_threshold), predict NEUTRAL.

        Returns (calibrated_label, top_score).
        """
        if not scores:
            return "NEUTRAL", 0.0
        score_map = {_normalize_label(s["label"]): s["score"] for s in scores}
        top_label = max(score_map, key=score_map.get)
        top_score = score_map[top_label]

        # Rule-based factual neutral detection takes priority
        if text and self._is_factual_neutral(text):
            return "NEUTRAL", top_score

        if top_label != "NEUTRAL":
            neutral_score = score_map.get("NEUTRAL", 0.0)
            margin = top_score - neutral_score
            if margin < self._neutral_margin_threshold:
                logger.debug(
                    "Calibrated %s -> NEUTRAL (margin=%.4f < %.2f)",
                    top_label,
                    margin,
                    self._neutral_margin_threshold,
                )
                return "NEUTRAL", top_score
        return top_label, top_score

    def _parse_pipeline_scores(self, raw_output) -> list[dict]:
        """Extract a flat list of {label, score} dicts from pipeline output."""
        if isinstance(raw_output, list) and len(raw_output) > 0:
            first = raw_output[0]
            if isinstance(first, list):
                return first
            if isinstance(first, dict):
                return raw_output
        return [{"label": "NEUTRAL", "score": 0.0}]

    def predict_single(self, text: str) -> SentimentResult:
        if not isinstance(text, str) or not text.strip():
            return SentimentResult(
                sentiment="NEUTRAL",
                confidence=0.0,
                model_version=self.version,
            )

        if self._pipeline is None:
            self.load_model()

        stripped = text.strip()
        raw_output = self._pipeline(stripped)
        scores = self._parse_pipeline_scores(raw_output)
        calibrated_label, top_score = self._calibrate_neutral(scores, stripped)

        return SentimentResult(
            sentiment=calibrated_label,
            confidence=top_score,
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
            for idx, result, text in zip(
                batch_indices, pipeline_results, batch_texts, strict=False
            ):
                scores = self._parse_pipeline_scores(result)
                calibrated_label, top_score = self._calibrate_neutral(scores, text)
                results[idx] = SentimentResult(
                    sentiment=calibrated_label,
                    confidence=top_score,
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
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        batch_size: int = DEFAULT_BATCH_SIZE,
        revision: str | None = DEFAULT_MODEL_REVISION,
    ):
        self.classifier = SentimentClassifier(model_name, batch_size, revision)
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
