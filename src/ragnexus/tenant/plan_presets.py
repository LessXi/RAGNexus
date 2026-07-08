"""租户套餐预设 — 三档 plan 的 features 与 limits 常量。

纯数据字典，零依赖，可直接序列化。
"""

PLAN_PRESETS = {
    "free": {
        "features": {
            "allowed_profiles": ["speed"],
            "hybrid_allowed": False,
            "rerank_allowed": False,
            "query_rewrite_allowed": False,
        },
        "limits": {
            "retrieve_qps": 3,
            "retrieve_daily": 500,
            "max_kb_per_retrieve": 1,
            "max_kb": 1,
            "max_documents_per_kb": 30,
            "max_processing_documents": 1,
        },
    },
    "standard": {
        "features": {
            "allowed_profiles": ["speed", "balanced", "custom"],
            "hybrid_allowed": True,
            "rerank_allowed": False,
            "query_rewrite_allowed": False,
        },
        "limits": {
            "retrieve_qps": 10,
            "retrieve_daily": 5000,
            "max_kb_per_retrieve": 3,
            "max_kb": 5,
            "max_documents_per_kb": 200,
            "max_processing_documents": 2,
        },
    },
    "pro": {
        "features": {
            "allowed_profiles": ["speed", "balanced", "quality", "custom"],
            "hybrid_allowed": True,
            "rerank_allowed": True,
            "query_rewrite_allowed": True,
        },
        "limits": {
            "retrieve_qps": 50,
            "retrieve_daily": 100000,
            "max_kb_per_retrieve": 5,
            "max_kb": 50,
            "max_documents_per_kb": 5000,
            "max_processing_documents": 10,
        },
    },
}
