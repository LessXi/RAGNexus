"""structchunk bridge 元数据映射测试。"""

import pytest
from ragnexus.infra.structchunk_bridge import chunk_markdown


class TestChunkMarkdown:
    def test_heading_path_from_breadcrumb(self):
        """header_breadcrumb → heading_path 映射正确，去 # 以 / 连接。"""
        content = "# 平台交易规则\n\n## 退款时效\n\n退款需在7日内申请。"
        chunks = chunk_markdown(content, max_chars=500)
        assert len(chunks) >= 1
        # 至少有一个 chunk 的 heading_path 含正确路径
        paths = [c["heading_path"] for c in chunks if c["heading_path"]]
        assert any("平台交易规则" in p for p in paths)

    def test_chunk_type_section(self):
        """普通段落 chunk_type 为 section。"""
        content = "## 说明\n\n这是一段普通文本。"
        chunks = chunk_markdown(content, max_chars=500)
        assert chunks[0]["chunk_type"] == "section"

    def test_chunk_type_table(self):
        """表格 chunk_type 为 table。"""
        content = "## 价格\n\n| 商品 | 价格 |\n|------|------|\n| A | 10 |"
        chunks = chunk_markdown(content, max_chars=500)
        table_chunks = [c for c in chunks if c["chunk_type"] == "table"]
        assert len(table_chunks) >= 1
        assert "商品" in table_chunks[0]["text"]

    def test_backward_compat_heading(self):
        """保留 heading 和 heading_level 向后兼容。"""
        content = "## 测试\n\n内容。"
        chunks = chunk_markdown(content, max_chars=500)
        assert chunks[0]["heading"] == "测试"
        assert chunks[0]["heading_level"] == 2

    def test_no_heading_path_for_plain_text(self):
        """无标题文本时 heading_path 为空。"""
        content = "这是纯文本内容，没有任何标题标记。"
        chunks = chunk_markdown(content, max_chars=500)
        assert chunks[0]["heading_path"] == ""

    def test_table_part_increment(self):
        """大表分组时 table_part 递增。"""
        header = (
            "| 列1 | 列2 | 列3 | 列4 | 列5 |\n|------|------|------|------|------|\n"
        )
        rows = "\n".join(
            [f"| r{i} | data{i} | x{i} | y{i} | z{i} |" for i in range(20)]
        )
        content = f"## 大表\n\n{header}{rows}"
        chunks = chunk_markdown(content, max_chars=500, table_max_rows=5)
        table_chunks = [c for c in chunks if c.get("table_part")]
        assert len(table_chunks) >= 2
        assert table_chunks[0]["table_part"] == 1
        assert table_chunks[1]["table_part"] == 2

    def test_horizontal_rule_not_isolated(self):
        """--- 分隔线不产生仅含分隔线的 chunk。"""
        content = "## 第一节\n\n内容A\n\n---\n\n## 第二节\n\n内容B"
        chunks = chunk_markdown(content, max_chars=500)
        # 每个 chunk 应包含有意义的文本
        for c in chunks:
            stripped = c["text"].strip()
            assert stripped, f"chunk 不应为空: {c}"
            # 不应是孤立的 ---
            assert stripped != "---", f"chunk 不应仅为分隔线: {c}"
