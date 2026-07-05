"""词表扩展器 — 基于 KB settings.synonyms 对有效查询追加扩展词。

规则：
- 遍历 effective_query 对每组 synonyms.terms 做中文精确子串匹配
- 英文 casefold 匹配
- 命中组的 expand 词去重后追加到 query 末尾
- 多组同时命中时 expand 去重合并
- 格式异常的 synonyms 静默跳过，不抛异常
"""

from __future__ import annotations


class SynonymExpander:
    """词表扩展器 — 基于 KB settings.synonyms 对有效查询追加扩展词。"""

    def expand(
        self, effective_query: str, synonyms: list[dict] | None
    ) -> tuple[str, bool, list[str]]:
        """扩展查询。

        参数:
            effective_query: 待扩展的查询字符串。
            synonyms: 词表列表，每组包含 terms（匹配词）和 expand（扩展词）。

        返回:
            (search_query, synonym_applied, expansions):
            - search_query: 追加扩展词后的查询
            - synonym_applied: 是否有词表命中
            - expansions: 实际追加的扩展词列表
        """
        if not synonyms:
            return effective_query, False, []

        all_expansions: list[str] = []
        query_lower = effective_query.lower()

        for group in synonyms:
            try:
                if not isinstance(group, dict):
                    continue

                terms = group.get("terms", [])
                expand_words = group.get("expand", [])
                if not isinstance(terms, list) or not isinstance(expand_words, list):
                    continue
            except Exception:
                continue

            # 检查是否命中
            hit = False
            for term in terms:
                try:
                    if not isinstance(term, str):
                        continue
                    if term.lower() in query_lower:
                        hit = True
                        break
                except Exception:
                    continue

            if hit:
                for word in expand_words:
                    try:
                        if isinstance(word, str) and word not in all_expansions:
                            all_expansions.append(word)
                    except Exception:
                        continue

        if not all_expansions:
            return effective_query, False, []

        # 去重后追加
        search_query = effective_query + " " + " ".join(all_expansions)
        return search_query, True, all_expansions
