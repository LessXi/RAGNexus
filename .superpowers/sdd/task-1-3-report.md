# Task 1.3 — Settings 增加 Celery 配置

**状态**: ✅ 完成

**提交**: `8a74d235e854e38e7a9ac535a774a9cf686cd85c`

**修改文件**: `src/ragnexus/config.py`
- 类 docstring: `"""51 个配置字段` → `"""54 个配置字段`
- 新增字段:
  - `CELERY_BROKER_URL: str = "redis://localhost:6379/0"`
  - `CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"`
  - `INDEX_TIMEOUT_MINUTES: int = 30`

**验证命令**:
```bash
python -c "from ragnexus.config import get_settings; s=get_settings(); print(s.CELERY_BROKER_URL, s.INDEX_TIMEOUT_MINUTES)"
```

**验证输出**: `redis://localhost:6379/0 30`
