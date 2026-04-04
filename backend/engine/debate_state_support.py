from __future__ import annotations

import re


CLAIM_STALE_AFTER_POSTS = 8
DEFINITION_STALE_AFTER_POSTS = 10
CONTRACT_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff]{2,24}", re.UNICODE)
