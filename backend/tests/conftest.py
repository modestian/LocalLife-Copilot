import pytest
from app.review_analysis import get_classifier


def pytest_addoption(parser):
    """注册自定义命令行参数 --run-model-tests"""
    parser.addoption(
        "--run-model-tests",
        action="store_true",
        default=False,
        help="Run tests that require loading real models",
    )


@pytest.fixture(scope="session")
def run_model_tests(request):
    """全局读取命令行开关"""
    return request.config.getoption("--run-model-tests")


@pytest.fixture(autouse=True)
def clear_classifier_cache():
    """每个测试用例执行前，自动清空分类器单例缓存，避免 Mock 和真实用例互相污染"""
    get_classifier.cache_clear()
    yield
    get_classifier.cache_clear()