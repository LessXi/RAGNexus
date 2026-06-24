# Task 6: CreateKnowledgeBaseUseCase — 完成

## 状态
- **提交**: `7663fd5` — `feat: add CreateKnowledgeBaseUseCase`
- **文件变更**: `+2 files, +90, -0`

## 实现文件

### `application/create_kb_use_case.py`
- `class CreateKnowledgeBaseUseCase`
  - `__init__(self, kb_repo: KnowledgeBasePort)` — DI 注入
  - `async execute(self, name: str) -> KnowledgeBase`
    - `name.strip()` 去除首尾空白
    - `1 <= len(name) <= 64` 校验 → 失败抛出 `ValidationError`（含 `errors=[{"field": "name", "reason": "长度必须在 1-64"}]`）
    - `name_key = name.lower()` 生成唯一键
    - 委托 `self._kb_repo.create(name=name, name_key=name_key)`

### `tests/unit/application/test_create_kb.py`
| 测试 | 场景 |
|---|---|
| `test_create_kb_success` | 有效名称 → 执行后返回 KnowledgeBase，验证 `assert_awaited_once_with(name="Test KB", name_key="test kb")` |
| `test_name_too_short` | 空字符串 / 纯空白 → ValidationError，repo.create 不被调用 |
| `test_name_too_long` | 65 字符 → ValidationError，repo.create 不被调用 |
| `test_duplicate_name` | repo.create 抛出 ConflictError → use case 透传 |

## 测试结果
```
pytest tests/unit/ -v → 18 passed in 0.18s
```
（全部 4 个新测试 + 14 个原有测试通过）

## 备注
- Spec 中 `1 <= len(name) <= 64` 使单字符名称合法。brief 中 "1-char name" 的表述已按 spec 修正（`test_name_too_short` 不包含 `"a"`）。
- Use case 为 async（`kb_repo.create` 是 `async def`）。
