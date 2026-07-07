"""structchunk 与 IndexingService 之间的薄适配层。

封装 metadata 映射（heading_path, chunk_type, table_part）
和 table_part 后处理逻辑。
"""

from ragnexus.infra.structchunk import chunk as _structchunk_chunk


def chunk_markdown(
    content: str,
    max_chars: int = 1500,
    table_max_rows: int = 10,
) -> list[dict]:
    """结构化 Markdown 切块，返回 IndexingService 兼容的 dict 列表。

    每个 dict 含:
    - text: str          — chunk 正文
    - heading_path: str  — 标题层级路径 (如 "H1 / H2")
    - chunk_type: str    — section | table | code | list | text
    - table_part: int    — 大表分组序号 (仅表格 chunk，可选)
    - heading: str       — 最近标题文本 (向后兼容)
    - heading_level: int — 标题层级 (向后兼容)
    """
    chunks = _structchunk_chunk(
        content,
        algorithm="hierarchical",
        max_chars=max_chars,
        preserve_table_header=True,
        sub_split_table=True,
    )

    result: list[dict] = []
    table_part_counter = 0

    for ch in chunks:
        md = ch.metadata

        # ── heading_path: 去 # 标记符，以 / 连接 ──
        breadcrumb_texts = [h.lstrip("#").strip() for h in md.header_breadcrumb]
        heading_path = " / ".join(breadcrumb_texts) if breadcrumb_texts else ""

        # ── chunk_type: source_element_type 映射 ──
        elem_type = (md.source_element_type or "paragraph").lower()
        type_map = {
            "paragraph": "section",
            "table": "table",
            "code": "code",
            "list": "list",
        }
        chunk_type = type_map.get(elem_type, "section")

        # ── heading / heading_level: 向后兼容 ──
        last_heading = ""
        last_level = 0
        if md.header_path:
            last = md.header_path[-1]
            last_heading = last.text
            last_level = last.level
        elif md.header_breadcrumb:
            last = md.header_breadcrumb[-1].lstrip("#").strip()
            last_heading = last
            last_level = md.header_breadcrumb[-1].count("#")

        piece: dict = {
            "text": ch.content,
            "heading_path": heading_path,
            "chunk_type": chunk_type,
            "heading": last_heading,
            "heading_level": last_level,
        }

        # ── table_part: 连续 table chunk 自增编号 ──
        if chunk_type == "table":
            table_part_counter += 1
            piece["table_part"] = table_part_counter
        else:
            table_part_counter = 0

        result.append(piece)

    return result
