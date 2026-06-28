"""LLMProvider 抽象基类 — 通用大模型调用抽象。

与 domain/ports.py 中的 Protocol 不同，LLMProvider 用 ABC 因为：
- 包含共享的 HTTP client 管理、并发控制、重试逻辑
- 子类需要继承这些共享实现，而非纯鸭子类型
- 这是 adapters 层内部抽象，不是 domain 端口
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """通用大模型调用抽象。所有 LLM 调用必须通过此接口。

    不定义在 domain/ports.py 中 — 这是 adapters 层内部抽象。
    后续 query rewrite、意图识别、评测辅助生成等也通过它调用大模型。

    子类必须实现 chat_json 方法，通过 OpenAI 兼容 API 调用大模型并返回 JSON 响应。
    """

    @abstractmethod
    async def chat_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        temperature: float = 0.0,
        timeout_seconds: int | None = None,
    ) -> dict:
        """调用大模型并返回 JSON 响应。

        参数:
            system_prompt: 系统提示词，定义模型角色和输出要求
            user_payload: 用户输入负载（会被 JSON 序列化后发送）
            temperature: 采样温度，0.0 表示确定性输出
            timeout_seconds: 可选超时秒数，None 使用默认值

        返回:
            模型返回的 JSON 响应（已解析为 dict）
        """
        ...
