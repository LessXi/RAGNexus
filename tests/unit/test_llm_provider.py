"""LLMProvider ABC 抽象基类测试。

TDD: RED → GREEN → REFACTOR。
运行: uv run pytest tests/unit/test_llm_provider.py -v
"""

import abc

import pytest

from ragnexus.adapters.llm.base import LLMProvider


class TestLLMProviderABC:
    """测试 LLMProvider 抽象基类的结构约束。"""

    def test_is_abc_subclass(self):
        """LLMProvider 必须是 abc.ABC 的直接或间接子类。"""
        assert issubclass(LLMProvider, abc.ABC)

    def test_cannot_instantiate_directly(self):
        """抽象类不能直接实例化——缺少 chat_json 实现时抛 TypeError。"""
        with pytest.raises(TypeError):
            LLMProvider()  # type: ignore[abstract]

    def test_has_chat_json_abstract_method(self):
        """LLMProvider 必须声明 chat_json 为抽象方法。"""
        assert hasattr(LLMProvider, "chat_json")
        method = LLMProvider.chat_json
        assert getattr(method, "__isabstractmethod__", False), "chat_json 必须是 @abstractmethod"

    def test_concrete_subclass_can_be_instantiated(self):
        """实现了 chat_json 的最小子类可以正常实例化。"""

        class ConcreteLLM(LLMProvider):
            async def chat_json(
                self,
                *,
                system_prompt: str,
                user_payload: dict,
                temperature: float = 0.0,
                timeout_seconds: int | None = None,
            ) -> dict:
                return {"result": "ok"}

        instance = ConcreteLLM()
        assert isinstance(instance, LLMProvider)
