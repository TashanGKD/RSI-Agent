"""The resident WeChat reply model port."""
from .codex_backend import CodexBackend


def load_model(path, *, verify_runtime=False):
    model = CodexBackend(path)
    if verify_runtime:
        model.check_runtime()
    return model
