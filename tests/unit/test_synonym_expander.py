"""SynonymExpander 词表扩展器单元测试。

验证中文精确子串匹配、英文 casefold 匹配、去重、格式异常容错等场景。
"""

from __future__ import annotations


from ragnexus.adapters.rewrite.synonym_expander import SynonymExpander


class TestSynonymExpander:
    """SynonymExpander.expand() 行为测试。"""

    def test_single_group_hit(self) -> None:
        """单组命中: query 含"背调" → 追加扩展词。"""
        expander = SynonymExpander()
        query = "背调流程"
        synonyms = [
            {"terms": ["背调"], "expand": ["背景调查", "标准问题清单"]},
        ]

        result, applied, expansions = expander.expand(query, synonyms)

        assert applied is True
        assert "背景调查" in result
        assert "标准问题清单" in result
        assert query in result  # 原查询保留
        assert "背景调查" in expansions
        assert "标准问题清单" in expansions

    def test_multi_group_hit_dedup(self) -> None:
        """多组命中+去重: query 含"背调"和"薪酬" → 去重合并扩展词。"""
        expander = SynonymExpander()
        query = "背调与薪酬定级"
        synonyms = [
            {"terms": ["背调"], "expand": ["背景调查", "标准问题清单"]},
            {"terms": ["薪酬", "薪资", "工资"], "expand": ["职级", "薪酬定级"]},
        ]

        result, applied, expansions = expander.expand(query, synonyms)

        assert applied is True
        assert "背景调查" in result
        assert "标准问题清单" in result
        assert "职级" in result
        assert "薪酬定级" in result
        assert len(expansions) == 4

    def test_no_match(self) -> None:
        """未命中: query 不含任何 terms → 返回原 query。"""
        expander = SynonymExpander()
        query = "RAG 架构设计"
        synonyms = [
            {"terms": ["背调"], "expand": ["背景调查"]},
            {"terms": ["薪酬"], "expand": ["职级"]},
        ]

        result, applied, expansions = expander.expand(query, synonyms)

        assert result == query
        assert applied is False
        assert expansions == []

    def test_english_casefold(self) -> None:
        """英文大小写: casefold 匹配。"RAG" 命中 "rag"。"""
        expander = SynonymExpander()
        query = "RAG 架构"
        synonyms = [
            {"terms": ["rag"], "expand": ["检索增强生成"]},
        ]

        result, applied, expansions = expander.expand(query, synonyms)

        assert applied is True
        assert "检索增强生成" in result
        assert "检索增强生成" in expansions

    def test_empty_synonyms(self) -> None:
        """空词表: synonyms=None / [] → 返回原 query。"""
        expander = SynonymExpander()
        query = "任意查询"

        # None
        r1, a1, e1 = expander.expand(query, None)
        assert r1 == query
        assert a1 is False
        assert e1 == []

        # 空列表
        r2, a2, e2 = expander.expand(query, [])
        assert r2 == query
        assert a2 is False
        assert e2 == []

    def test_malformed_synonyms_silent_skip(self) -> None:
        """格式异常容错: 畸形 synonyms 结构不抛异常，正常组仍生效。"""
        expander = SynonymExpander()
        query = "背调测试"
        synonyms: list = [
            {"terms": ["背调"], "expand": ["背景调查"]},  # 正常组
            "not a dict",  # 非 dict
            {"expand": ["缺 terms"]},  # 缺 terms 键
            {"terms": "not list", "expand": ["x"]},  # terms 非 list
            {"terms": ["背调"], "expand": "not list"},  # expand 非 list
            {"terms": [123, None], "expand": ["数字"]},  # terms 含非字符串
            {"terms": ["背调"], "expand": [456, None]},  # expand 含非字符串
            {"terms": [], "expand": ["空 terms"]},  # 空 terms — 不命中但不报错
        ]

        result, applied, expansions = expander.expand(query, synonyms)

        # 格式异常组静默跳过，不应抛异常
        assert applied is True
        assert "背景调查" in result
        assert expansions == ["背景调查"]  # 只有正常组命中

    def test_cross_group_expand_dedup(self) -> None:
        """跨组扩展词去重: 两组 expand 含相同词 → 只追加一次。"""
        expander = SynonymExpander()
        query = "背调与薪酬制度"
        synonyms = [
            {"terms": ["背调"], "expand": ["背景调查", "薪酬定级"]},
            {"terms": ["薪酬"], "expand": ["职级", "背景调查"]},  # "背景调查" 重复
        ]

        result, applied, expansions = expander.expand(query, synonyms)

        assert applied is True
        # "背景调查" 只出现一次
        assert result.count("背景调查") == 1
        assert "职级" in expansions
        assert "薪酬定级" in expansions
        assert len(expansions) == 3  # 去重后 3 个不同词
