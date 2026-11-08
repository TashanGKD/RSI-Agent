"""Offline dependency check in the configured Harness Python; no Session/provider."""
from importlib import metadata
import json
import os
from pathlib import Path


expected = dict(line.split('==') for line in
    (Path(__file__).resolve().parents[2] / 'requirements-harness.txt').read_text().splitlines() if line.strip())
versions = {}
for package in expected:
    try:
        versions[package] = metadata.version(package)
    except metadata.PackageNotFoundError:
        versions[package] = None

sdk_ready = runtime_ready = False
try:
    from deepseek_harness import DeepSeekHarness
    sdk_ready = versions['deepseek-harness-sdk'] == expected['deepseek-harness-sdk']
except ImportError:
    pass
try:
    from deepseek_harness_runtime import bundled_runtime_path
    runtime_ready = (versions['deepseek-harness-runtime-bin'] == expected['deepseek-harness-runtime-bin']
                     and os.access(bundled_runtime_path(), os.X_OK))
except (ImportError, OSError, ValueError):
    pass

print(json.dumps({'sdk_ready': sdk_ready, 'runtime_ready': runtime_ready}))
