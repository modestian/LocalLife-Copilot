from typing import Literal

from pydantic import BaseModel, Field


class SentimentResult(BaseModel):
    sentiment: Literal["POSITIVE", "NEUTRAL", "NEGATIVE"] = Field(
        description="情感标签：好评/中性/差评"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="置信度，范围 [0, 1]"
    )
    model_version: str = Field(
        description="模型版本标识"
    )


class BatchSentimentResult(BaseModel):
    results: list[SentimentResult] = Field(
        description="批量推理结果列表"
    )
    model_version: str = Field(
        description="使用的模型版本"
    )
    total_count: int = Field(
        description="输入点评总数"
    )
    processed_count: int = Field(
        description="成功处理的数量"
    )
