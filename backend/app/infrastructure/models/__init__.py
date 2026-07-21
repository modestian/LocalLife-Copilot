"""模型适配器统一接口。

具体设计 §9.5：Model Adapter 接口统一 predict(batch)；
配置切换只改变注册版本，不让业务代码感知 PEFT 细节。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelAdapter(Protocol):
    """统一模型推理接口，屏蔽全参数/LoRA/QLoRA 加载差异。

    现有 ``SentimentClassifier`` 天然满足此协议
    （``version`` 属性 + ``predict_batch`` 方法），
    后续 LoRA Adapter 加载器只需实现同一接口即可透明替换。
    """

    @property
    def model_version(self) -> str:
        """返回模型版本标识，格式 ``base_model@revision`` 或 ``adapter@version``。"""
        ...

    def predict(self, batch: list[str]) -> list[dict]:
        """批量推理。

        Args:
            batch: 待推理文本列表。

        Returns:
            每条文本对应的 ``{"label": str, "score": float}`` 列表。
        """
        ...
