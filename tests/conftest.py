"""Test-suite-wide setup. Not a mirror of a backend/ module (same exception
as tests/fakes.py) — pytest's own convention for this file name/location.
"""

import os

# sentence-transformers/huggingface_hub re-validate their local cache against
# the Hub with a burst of HEAD requests on every fresh model load by default,
# even when the weights are already fully cached — adding real seconds of
# network latency to every test that constructs a new Embedder/Reranker. This
# repo's models are already downloaded (CLAUDE.md §14's setup-script
# pre-download step), so tests run fully offline. This is scoped to the test
# suite only, not set globally, so a genuinely fresh environment's first-ever
# model download (outside pytest) is unaffected.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
