from pathlib import Path

from pydantic import BaseModel


class ReviewAnalysisConfig(BaseModel):
    model_name_or_path: str = "uer/roberta-base-finetuned-dianping-chinese"
    max_length: int = 256
    batch_size: int = 32
    device: str = "cpu"
    label_mapping: dict[int, str] = {0: "NEGATIVE", 1: "NEUTRAL", 2: "POSITIVE"}


_config = ReviewAnalysisConfig()


def get_review_analysis_config() -> ReviewAnalysisConfig:
    return _config


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def get_data_dir() -> Path:
    return get_project_root() / "app" / "data"
