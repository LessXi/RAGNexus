import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Switch } from '@base-ui/react/switch';
import { fetchTree, retrieve } from '@/services/api';
import type { TreeItem, KBItem, RetrieveResponse } from '@/types/api';
import { Search, Loader2, ChevronDown, ChevronRight, AlertTriangle, Info } from 'lucide-react';

/* ── 类型 ── */

/** 扁平化 KB 选项 */
interface KbOption {
  kb_id: string;
  name: string;
  tenant_id: string;
}

/** 检索模式 */
type RetrieveMode = 'vector' | 'bm25' | 'hybrid';

/* ── 工具 ── */

/** 从 tree 中扁平化所有 KB 选项 */
function flattenKBs(tree: TreeItem[]): KbOption[] {
  const result: KbOption[] = [];
  for (const tenant of tree) {
    for (const kb of tenant.knowledge_bases) {
      result.push({
        kb_id: kb.kb_id,
        name: kb.name,
        tenant_id: tenant.tenant_id,
      });
    }
  }
  return result;
}

/* ── 组件 ── */

export default function RetrievePage() {
  const [searchParams] = useSearchParams();

  /* ── tree 数据 ── */
  const [tree, setTree] = useState<TreeItem[]>([]);
  const [kbOptions, setKbOptions] = useState<KbOption[]>([]);
  const [treeLoading, setTreeLoading] = useState(true);
  const [treeError, setTreeError] = useState<string | null>(null);

  /* ── 表单 ── */
  const [selectedKbId, setSelectedKbId] = useState('');
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(5);
  const [mode, setMode] = useState<RetrieveMode>('hybrid');
  const [vectorTopK, setVectorTopK] = useState(20);
  const [bm25TopK, setBm25TopK] = useState(20);
  const [rrfK, setRrfK] = useState(60);
  const [rerankEnabled, setRerankEnabled] = useState(false);
  const [rerankTopN, setRerankTopN] = useState(5);
  const [rewriteEnabled, setRewriteEnabled] = useState(false);

  /* ── 结果 ── */
  const [results, setResults] = useState<RetrieveResponse | null>(null);
  const [retrieving, setRetrieving] = useState(false);
  const [retrieveError, setRetrieveError] = useState<string | null>(null);

  /* ── 折叠 ── */
  const [configExpanded, setConfigExpanded] = useState(true);
  const [expandedHits, setExpandedHits] = useState<Set<string>>(new Set());

  /* ── 加载 tree ── */
  const loadTree = useCallback(async () => {
    setTreeLoading(true);
    setTreeError(null);
    try {
      const data = await fetchTree();
      setTree(data);
      const opts = flattenKBs(data);
      setKbOptions(opts);

      // URL 预填
      const kbId = searchParams.get('kb_id') ?? '';
      if (kbId) setSelectedKbId(kbId);
    } catch (err) {
      setTreeError(err instanceof Error ? err.message : '加载知识库列表失败');
    } finally {
      setTreeLoading(false);
    }
  }, [searchParams]);

  useEffect(() => {
    loadTree();
  }, [loadTree]);

  /* ── 检索 ── */
  const handleRetrieve = async () => {
    if (!query.trim() || !selectedKbId) return;

    setRetrieving(true);
    setRetrieveError(null);
    setResults(null);

    try {
      const body: Parameters<typeof retrieve>[0] = {
        query: query.trim(),
        kb_ids: [selectedKbId],
        top_k: topK,
        mode,
      };

      if (mode === 'hybrid') {
        body.vector_top_k = vectorTopK;
        body.bm25_top_k = bm25TopK;
        body.rrf_k = rrfK;
      }

      if (rerankEnabled) {
        body.rerank = { enabled: true, top_n: rerankTopN };
      }

      if (rewriteEnabled) {
        body.query_options = { enabled: true, strategy: 'rewrite' };
      }

      const res = await retrieve(body);
      setResults(res);
    } catch (err) {
      setRetrieveError(err instanceof Error ? err.message : '检索请求失败');
    } finally {
      setRetrieving(false);
    }
  };

  /* ── 派生状态 ── */
  const canRetrieve = query.trim().length > 0 && selectedKbId.length > 0;
  const hits = results?.data?.hits ?? [];
  const meta = results?.data?.meta ?? null;

  /* ── 渲染 ── */

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-foreground">检索调试</h1>

      {/* ═══════ Card 1: 检索配置 ═══════ */}
      <div className="rounded-xl border border-border bg-card shadow-sm">
        <button
          type="button"
          className="flex w-full items-center gap-2 px-5 py-3 text-left text-base font-semibold text-foreground"
          onClick={() => setConfigExpanded((v) => !v)}
          aria-expanded={configExpanded}
        >
          {configExpanded ? (
            <ChevronDown className="size-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-4 text-muted-foreground" />
          )}
          检索配置
        </button>

        {configExpanded && (
          <div className="border-t border-border px-5 pb-5 pt-4 space-y-4">
            {treeLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                加载知识库列表...
              </div>
            )}
            {treeError && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {treeError}
              </div>
            )}

            {/* 知识库选择 */}
            <div>
              <label
                htmlFor="kb-select"
                className="mb-1 inline-flex items-center gap-1.5 text-sm font-medium text-foreground"
              >
                知识库 <span className="text-red-500">*</span>
                <span className="group relative inline-flex items-center">
                  <Info className="size-4 cursor-help text-muted-foreground hover:text-foreground transition-colors" />
                  <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 whitespace-nowrap rounded-md border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground opacity-0 shadow-md transition-opacity group-hover:opacity-100">
                    通过 API Key 自动识别租户，无需手动选择
                  </span>
                </span>
              </label>
              <select
                id="kb-select"
                value={selectedKbId}
                onChange={(e) => setSelectedKbId(e.target.value)}
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-ring/20"
                aria-label="知识库"
              >
                <option value="">请选择知识库</option>
                {kbOptions.map((o) => (
                  <option key={o.kb_id} value={o.kb_id}>
                    {o.name} ({o.tenant_id})
                  </option>
                ))}
              </select>
            </div>

            {/* top_k */}
            <div>
              <label className="mb-1 block text-sm font-medium text-foreground">
                top_k (1–50)
              </label>
              <input
                type="number"
                min={1}
                max={50}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className="w-32 rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-ring/20"
              />
            </div>

            {/* 模式 Tabs */}
            <div>
              <label className="mb-1 block text-sm font-medium text-foreground">
                检索模式
              </label>
              <div
                className="inline-flex rounded-lg border border-border bg-muted p-0.5"
                role="tablist"
              >
                {(['vector', 'bm25', 'hybrid'] as const).map((m) => (
                  <button
                    key={m}
                    role="tab"
                    type="button"
                    aria-selected={mode === m}
                    onClick={() => setMode(m)}
                    className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${mode === m
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                      }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            {/* hybrid 参数 */}
            {mode === 'hybrid' && (
              <div className="grid grid-cols-3 gap-4 rounded-lg border border-border bg-muted/30 p-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    vector_top_k (1–200)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={vectorTopK}
                    onChange={(e) => setVectorTopK(Number(e.target.value))}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-ring/20"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    bm25_top_k (1–200)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={bm25TopK}
                    onChange={(e) => setBm25TopK(Number(e.target.value))}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-ring/20"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    rrf_k (1–200)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={rrfK}
                    onChange={(e) => setRrfK(Number(e.target.value))}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-ring/20"
                  />
                </div>
              </div>
            )}

            {/* rerank */}
            <div className="flex items-center gap-3">
              <Switch.Root
                checked={rerankEnabled}
                onCheckedChange={setRerankEnabled}
                className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent bg-muted transition-colors data-[checked]:bg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <Switch.Thumb className="pointer-events-none block size-4 rounded-full bg-background shadow-lg ring-0 transition-transform data-[checked]:translate-x-4" />
              </Switch.Root>
              <span className="text-sm font-medium text-foreground">Rerank</span>
              {rerankEnabled && (
                <div className="flex items-center gap-2">
                  <label className="text-sm text-muted-foreground">top_n</label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={rerankTopN}
                    onChange={(e) => setRerankTopN(Number(e.target.value))}
                    className="w-20 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-ring/20"
                  />
                </div>
              )}
            </div>

            {/* query 改写 */}
            <div className="flex items-center gap-3">
              <Switch.Root
                checked={rewriteEnabled}
                onCheckedChange={setRewriteEnabled}
                className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent bg-muted transition-colors data-[checked]:bg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <Switch.Thumb className="pointer-events-none block size-4 rounded-full bg-background shadow-lg ring-0 transition-transform data-[checked]:translate-x-4" />
              </Switch.Root>
              <span className="text-sm font-medium text-foreground">启用 query 改写</span>
              <span className="group relative inline-flex items-center">
                <Info className="size-4 cursor-help text-muted-foreground hover:text-foreground transition-colors" />
                <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 whitespace-nowrap rounded-md border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground opacity-0 shadow-md transition-opacity group-hover:opacity-100">
                  用 AI 把口语问题改成更好搜的说法
                </span>
              </span>
            </div>
          </div>
        )}
      </div>

      {/* ═══════ Card 2: 检索结果 ═══════ */}
      <div className="rounded-xl border border-border bg-card shadow-sm">
        <div className="px-5 py-3 border-b border-border">
          <h2 className="text-base font-semibold text-foreground">检索结果</h2>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* query 输入 + 检索按钮 */}
          <div className="flex gap-3">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="输入检索内容..."
              onKeyDown={(e) => {
                if (e.key === 'Enter' && canRetrieve && !retrieving) {
                  handleRetrieve();
                }
              }}
              className="flex-1 rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-ring/20"
            />
            <button
              type="button"
              onClick={handleRetrieve}
              disabled={!canRetrieve || retrieving}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {retrieving ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  检索中...
                </>
              ) : (
                <>
                  <Search className="size-4" />
                  检索
                </>
              )}
            </button>
          </div>

          {/* 错误态 */}
          {retrieveError && (
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <div>
                <p className="font-medium">检索失败</p>
                <p className="text-red-600">{retrieveError}</p>
              </div>
              <button
                type="button"
                onClick={handleRetrieve}
                className="ml-auto shrink-0 rounded-md bg-red-100 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-200 transition-colors"
              >
                重试
              </button>
            </div>
          )}

          {/* 结果列表 */}
          {hits.length > 0 && (
            <div className="space-y-3">
              {hits.map((hit) => {
                const isExpanded = expandedHits.has(hit.chunk_id);
                const preview =
                  hit.text.length > 120 && !isExpanded
                    ? hit.text.slice(0, 120) + '...'
                    : hit.text;

                return (
                  <div
                    key={hit.chunk_id}
                    className="rounded-lg border border-border bg-background p-4"
                  >
                    {/* 标题 + 分数 */}
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-foreground">
                        {hit.title}
                      </span>
                      {/* 分数 chips — 有值才显示 */}
                      <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                        score: {hit.score.toFixed(4)}
                      </span>
                      {hit.vector_score != null && (
                        <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                          vec: {hit.vector_score.toFixed(4)}
                        </span>
                      )}
                      {hit.bm25_score != null && (
                        <span className="inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                          bm25: {hit.bm25_score.toFixed(4)}
                        </span>
                      )}
                      {hit.rerank_score != null && (
                        <span className="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                          rerank: {hit.rerank_score.toFixed(4)}
                        </span>
                      )}
                    </div>

                    {/* 内容 */}
                    <div className="mb-2">
                      <p className="whitespace-pre-wrap text-sm text-muted-foreground leading-relaxed">
                        {preview}
                      </p>
                      {hit.text.length > 120 && (
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedHits((prev) => {
                              const next = new Set(prev);
                              if (isExpanded) next.delete(hit.chunk_id);
                              else next.add(hit.chunk_id);
                              return next;
                            })
                          }
                          className="mt-1 text-xs text-primary hover:underline"
                        >
                          {isExpanded ? '收起' : '展开全部'}
                        </button>
                      )}
                    </div>

                    {/* 元信息 */}
                    <div className="flex gap-4 text-xs text-muted-foreground/70">
                      <span>chunk: {hit.chunk_id}</span>
                      <span>doc: {hit.doc_id}</span>
                      <span>kb: {hit.kb_id}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* 空状态 */}
          {!retrieving && !retrieveError && hits.length === 0 && (
            <p className="text-sm text-muted-foreground">
              输入查询内容并选择知识库后点击检索
            </p>
          )}
        </div>
      </div>

      {/* ═══════ Card 3: 运行摘要 ═══════ */}
      <div className="rounded-xl border border-border bg-card shadow-sm">
        <div className="px-5 py-3 border-b border-border">
          <h2 className="text-base font-semibold text-foreground">运行摘要</h2>
        </div>

        <div className="px-5 py-4">
          {meta ? (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-4">
                <div className="rounded-lg bg-muted/50 px-3 py-2">
                  <div className="text-xs text-muted-foreground">total</div>
                  <div className="text-lg font-semibold text-foreground">
                    {meta.total}
                  </div>
                </div>
                <div className="rounded-lg bg-muted/50 px-3 py-2">
                  <div className="text-xs text-muted-foreground">latency_ms</div>
                  <div className="text-lg font-semibold text-foreground">
                    {meta.latency_ms.toFixed(1)}
                  </div>
                </div>
                <div className="rounded-lg bg-muted/50 px-3 py-2">
                  <div className="text-xs text-muted-foreground">mode</div>
                  <div className="text-lg font-semibold text-foreground">
                    {meta.mode}
                  </div>
                </div>
                <div className="rounded-lg bg-muted/50 px-3 py-2">
                  <div className="text-xs text-muted-foreground">vector_count</div>
                  <div className="text-base font-semibold text-foreground">
                    {meta.vector_count}
                  </div>
                </div>
                <div className="rounded-lg bg-muted/50 px-3 py-2">
                  <div className="text-xs text-muted-foreground">bm25_count</div>
                  <div className="text-base font-semibold text-foreground">
                    {meta.bm25_count}
                  </div>
                </div>
                <div className="rounded-lg bg-muted/50 px-3 py-2">
                  <div className="text-xs text-muted-foreground">fused_count</div>
                  <div className="text-base font-semibold text-foreground">
                    {meta.fused_count}
                  </div>
                </div>
              </div>

              {meta.rerank_model && (
                <div className="rounded-lg bg-muted/50 px-3 py-2">
                  <div className="text-xs text-muted-foreground">rerank_model</div>
                  <div className="text-sm font-medium text-foreground">
                    {meta.rerank_model}
                  </div>
                </div>
              )}

              {meta.degraded && (
                <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  <div>
                    <p className="font-medium">服务降级</p>
                    {meta.degraded_reason && (
                      <p className="text-red-600">{meta.degraded_reason}</p>
                    )}
                  </div>
                </div>
              )}

              {meta.query_processing && (
                <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-3">
                  <div className="text-sm font-semibold text-foreground">Query 处理</div>

                  {/* 三句对比 */}
                  <div className="grid grid-cols-1 gap-2">
                    <div className="flex items-start gap-2">
                      <span className="shrink-0 text-xs text-muted-foreground w-16">原话</span>
                      <span className="text-sm text-foreground">{meta.query_processing.raw_query}</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="shrink-0 text-xs text-muted-foreground w-16">改写后</span>
                      <span className="text-sm text-foreground">{meta.query_processing.effective_query}</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="shrink-0 text-xs text-muted-foreground w-16">最终检索句</span>
                      <span className="text-sm text-foreground">{meta.query_processing.search_query}</span>
                    </div>
                  </div>

                  {/* 改写耗时 */}
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">改写耗时</span>
                    <span className="text-sm font-medium text-foreground">
                      {meta.query_processing.rewrite_latency_ms.toFixed(1)} ms
                    </span>
                  </div>

                  {/* 降级提示 */}
                  {meta.query_processing.degraded && (
                    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                      <div>
                        <p className="font-medium">Query 改写降级</p>
                        {meta.query_processing.degraded_reason && (
                          <p className="text-red-600">{meta.query_processing.degraded_reason}</p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* 扩展词列表 */}
                  {meta.query_processing.synonym_expansions.length > 0 && (
                    <div>
                      <span className="text-xs text-muted-foreground">扩展词</span>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {meta.query_processing.synonym_expansions.map((word: string) => (
                          <span
                            key={word}
                            className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
                          >
                            {word}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">尚未执行检索</p>
          )}
        </div>
      </div>
    </div>
  );
}
