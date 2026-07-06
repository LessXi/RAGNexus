"""检索 profile 预设 — 四档标准 profile（不含 custom）。

custom profile 由请求参数动态决定，不在预设常量中。
"""

RETRIEVE_PROFILE_PRESETS = {
    "speed": {
        "mode": "vector",
        "top_k": 3,
        "rerank_enabled": False,
        "query_options": {"enabled": False},
    },
    "balanced": {
        "mode": "hybrid",
        "top_k": 5,
        "rerank_enabled": False,
        "query_options": {"enabled": False},
    },
    "quality": {
        "mode": "hybrid",
        "top_k": 8,
        "rerank_enabled": True,
        "rerank_top_n": 5,
        "query_options": {"enabled": True, "strategy": "rewrite"},
    },
}
