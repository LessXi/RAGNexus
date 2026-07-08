import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { RetrieveResponse } from '@/types/api';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/* ── mocks ── */
const mockFetchTree = vi.fn();
const mockRetrieve = vi.fn();
const defaultParams = new URLSearchParams();
const mockUseSearchParams = vi.fn(() => [defaultParams, vi.fn()]);

vi.mock('@/services/api', () => ({
 fetchTree: (...args: unknown[]) => mockFetchTree(...args),
}));

vi.mock('@/services/ragService', () => ({
 retrieve: (...args: unknown[]) => mockRetrieve(...args),
}));

vi.mock('@/services/authService', () => ({
 fetchAuthMe: vi.fn().mockResolvedValue(null),
}));

vi.mock('react-router-dom', async () => {
 const actual = await vi.importActual('react-router-dom');
 return {
  ...(actual as object),
  useSearchParams: () => mockUseSearchParams(),
 };
});

/* ── 引入被测页面（mock 之后） ── */
import RetrievePage from './retrieve';

/* ── helpers ── */
function renderPage(searchParams?: URLSearchParams) {
 mockUseSearchParams.mockReturnValue([
  searchParams ?? defaultParams,
  vi.fn(),
 ]);

 const qc = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
 });
 return render(
  <QueryClientProvider client={qc}>
   <MemoryRouter initialEntries={['/retrieve']}>
    <RetrievePage />
   </MemoryRouter>
  </QueryClientProvider>,
 );
}

/** 获取检索按钮（精确匹配"检索"文字） */
function getRetrieveButton() {
 return screen.getByRole('button', { name: '检索' });
}

/** 构造典型 tree 数据 — 匹配 TreeItem / KBItem 类型 */
function mockTree() {
 return [
  {
   tenant_id: 'tenant_a',
   knowledge_bases: [
    {
     kb_id: 'kb_1',
     name: '知识库 A-1',
     description: '',
     document_count: 3,
     total_chunks: 100,
     created_at: '2025-01-01T00:00:00Z',
     documents: [],
    },
    {
     kb_id: 'kb_2',
     name: '知识库 A-2',
     description: '',
     document_count: 0,
     total_chunks: 0,
     created_at: '2025-01-02T00:00:00Z',
     documents: [],
    },
   ],
  },
  {
   tenant_id: 'tenant_b',
   knowledge_bases: [
    {
     kb_id: 'kb_3',
     name: '知识库 B-1',
     description: '',
     document_count: 5,
     total_chunks: 200,
     created_at: '2025-02-01T00:00:00Z',
     documents: [],
    },
   ],
  },
 ];
}

/** 构造典型 retrieve 响应 */
function mockRetrieveSuccess(): RetrieveResponse {
 return {
  code: 0,
  data: {
   kb_ids: ['kb_1'],
   hits: [
    {
     chunk_id: 'chunk-1',
     kb_id: 'kb_1',
     kb_name: '知识库 A-1',
     doc_id: 'doc-1',
     score: 0.95,
     text:
      '这是第一条检索结果的文本内容，包含足够多的字符来测试折叠功能。' +
      'X'.repeat(200),
     title: '文档一：RAG 入门',
     metadata: { source: 'manual' },
     vector_score: 0.92,
     bm25_score: null,
     rerank_score: null,
    },
    {
     chunk_id: 'chunk-2',
     kb_id: 'kb_1',
     kb_name: '知识库 A-1',
     doc_id: 'doc-2',
     score: 0.78,
     text: '第二条结果内容较短。',
     title: '文档二：Embedding 原理',
     metadata: {},
     vector_score: null,
     bm25_score: 0.78,
     rerank_score: 0.81,
    },
   ],
   meta: {
    total: 2,
    latency_ms: 45.2,
    mode: 'hybrid',
    vector_count: 10,
    bm25_count: 10,
    fused_count: 5,
    rerank_model: 'bge-reranker-v2-m3',
    degraded: false,
    degraded_reason: null,
    multi_kb: false,
    fusion: 'none',
    kb_count: 1,
   },
  },
  metadata: {},
 };
}

/** 构造多库联查响应 */
function mockMultiKbSuccess(): RetrieveResponse {
 return {
  code: 0,
  data: {
   kb_ids: ['kb_1', 'kb_3'],
   hits: [
    {
     chunk_id: 'chunk-1',
     kb_id: 'kb_1',
     kb_name: '知识库 A-1',
     doc_id: 'doc-1',
     score: 0.95,
     text: '来自知识库 A-1 的结果。',
     title: '文档一',
     metadata: {},
     vector_score: 0.92,
     bm25_score: null,
     rerank_score: null,
    },
    {
     chunk_id: 'chunk-3',
     kb_id: 'kb_3',
     kb_name: '知识库 B-1',
     doc_id: 'doc-3',
     score: 0.85,
     text: '来自知识库 B-1 的结果。',
     title: '文档三',
     metadata: {},
     vector_score: null,
     bm25_score: 0.88,
     rerank_score: null,
    },
   ],
   meta: {
    total: 2,
    latency_ms: 78.5,
    mode: 'hybrid',
    vector_count: 10,
    bm25_count: 10,
    fused_count: 5,
    rerank_model: null,
    degraded: false,
    degraded_reason: null,
    multi_kb: true,
    fusion: 'rrf',
    kb_count: 2,
   },
  },
  metadata: {},
 };
}

describe('RetrievePage', () => {
 beforeEach(() => {
  vi.clearAllMocks();
  mockFetchTree.mockResolvedValue(mockTree());
  mockUseSearchParams.mockReturnValue([defaultParams, vi.fn()]);
 });

 /* ═══════════════════════════════════════════
  *  基础渲染
  * ═══════════════════════════════════════════ */

 it('应渲染三个 Card 标题', async () => {
  renderPage();

  await waitFor(() => {
   expect(screen.getByText('检索配置')).toBeInTheDocument();
  });
  expect(screen.getByText('检索结果')).toBeInTheDocument();
  expect(screen.getByText('运行摘要')).toBeInTheDocument();
 });

 it('页面挂载后应调用 fetchTree 加载租户/KB 列表', async () => {
  renderPage();
  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });
 });

 /* ═══════════════════════════════════════════
  *  Checkbox 多选 KB 列表
  * ═══════════════════════════════════════════ */

 it('应渲染 Checkbox 列表替代 select 下拉框', async () => {
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  // 不应存在 KB select 元素
  expect(screen.queryByRole('combobox', { name: /知识库/i })).toBeNull();

  // 应渲染三个 KB 的 checkbox
  expect(screen.getByLabelText('知识库 A-1')).toBeInTheDocument();
  expect(screen.getByLabelText('知识库 A-2')).toBeInTheDocument();
  expect(screen.getByLabelText('知识库 B-1')).toBeInTheDocument();
 });

 it('URL 带 ?kb_id=yyy 时应默认勾选对应 KB', async () => {
  const sp = new URLSearchParams('?kb_id=kb_2');
  renderPage(sp);

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  const checkbox = screen.getByLabelText('知识库 A-2') as HTMLInputElement;
  expect(checkbox.checked).toBe(true);
 });

 it('未勾选任何 KB 时检索按钮应 disabled', async () => {
  renderPage();
  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  expect(getRetrieveButton()).toBeDisabled();
 });

 it('未输入 query 时即使勾选 KB 检索按钮也应 disabled', async () => {
  renderPage();
  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  await userEvent.click(screen.getByLabelText('知识库 A-1'));
  expect(getRetrieveButton()).toBeDisabled();
 });

 /* ═══════════════════════════════════════════
  *  检索执行
  * ═══════════════════════════════════════════ */

 it('勾选 KB 并输入 query 后点击检索应调用 retrieve API', async () => {
  mockRetrieve.mockResolvedValue(mockRetrieveSuccess());
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  await userEvent.click(screen.getByLabelText('知识库 A-1'));

  const queryInput = screen.getByPlaceholderText(/输入检索内容/i);
  await userEvent.type(queryInput, 'RAG 入门教程');

  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   expect(mockRetrieve).toHaveBeenCalledWith(
    expect.objectContaining({
     query: 'RAG 入门教程',
     kb_ids: ['kb_1'],
    }),
   );
  });
 });

 it('勾选多个 KB 后检索应传递 kb_ids 数组', async () => {
  mockRetrieve.mockResolvedValue(mockMultiKbSuccess());
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  await userEvent.click(screen.getByLabelText('知识库 A-1'));
  await userEvent.click(screen.getByLabelText('知识库 B-1'));

  const queryInput = screen.getByPlaceholderText(/输入检索内容/i);
  await userEvent.type(queryInput, '多库测试');

  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   expect(mockRetrieve).toHaveBeenCalledWith(
    expect.objectContaining({
     query: '多库测试',
     kb_ids: ['kb_1', 'kb_3'],
    }),
   );
  });
 });

 /* ═══════════════════════════════════════════
  *  结果显示
  * ═══════════════════════════════════════════ */

 it('检索成功后应显示 hit 列表', async () => {
  mockRetrieve.mockResolvedValue(mockRetrieveSuccess());
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  await userEvent.click(screen.getByLabelText('知识库 A-1'));
  await userEvent.type(screen.getByPlaceholderText(/输入检索内容/i), 'test query');
  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   expect(screen.getByText('文档一：RAG 入门')).toBeInTheDocument();
   expect(screen.getByText('文档二：Embedding 原理')).toBeInTheDocument();
  });
 });

 it('检索成功后应显示运行摘要 meta 信息', async () => {
  mockRetrieve.mockResolvedValue(mockRetrieveSuccess());
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  await userEvent.click(screen.getByLabelText('知识库 A-1'));
  await userEvent.type(screen.getByPlaceholderText(/输入检索内容/i), 'test');
  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   expect(screen.getByText('2')).toBeInTheDocument(); // total
   expect(screen.getByText(/45\.2/)).toBeInTheDocument(); // latency
   const modeElements = screen.getAllByText('hybrid');
   expect(modeElements.length).toBeGreaterThanOrEqual(1);
  });
 });

 it('分数 chips 应有值才显示，null 隐藏', async () => {
  mockRetrieve.mockResolvedValue(mockRetrieveSuccess());
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  await userEvent.click(screen.getByLabelText('知识库 A-1'));
  await userEvent.type(screen.getByPlaceholderText(/输入检索内容/i), 'test');
  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   expect(screen.getByText(/^score: 0\.9500$/)).toBeInTheDocument();
   expect(screen.getByText(/^vec: 0\.9200$/)).toBeInTheDocument();
   expect(screen.getByText(/^score: 0\.7800$/)).toBeInTheDocument();
   expect(screen.getByText(/^bm25: 0\.7800$/)).toBeInTheDocument();
   expect(screen.getByText(/^rerank: 0\.8100$/)).toBeInTheDocument();
  });
 });

 /* ═══════════════════════════════════════════
  *  来源库 Badge
  * ═══════════════════════════════════════════ */

 it('每条 hit 应显示来源库 Badge（kb_name）', async () => {
  mockRetrieve.mockResolvedValue(mockMultiKbSuccess());
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  await userEvent.click(screen.getByLabelText('知识库 A-1'));
  await userEvent.click(screen.getByLabelText('知识库 B-1'));
  await userEvent.type(screen.getByPlaceholderText(/输入检索内容/i), 'test');
  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   // 每个 KB 名称同时出现在 checkbox label 和 hit Badge 中
   expect(screen.getAllByText('知识库 A-1').length).toBeGreaterThanOrEqual(2);
   expect(screen.getAllByText('知识库 B-1').length).toBeGreaterThanOrEqual(2);
  });
 });

 /* ═══════════════════════════════════════════
  *  运行摘要区（多库联查）
  * ═══════════════════════════════════════════ */

 it('多库联查时摘要区应显示联查信息', async () => {
  mockRetrieve.mockResolvedValue(mockMultiKbSuccess());
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  await userEvent.click(screen.getByLabelText('知识库 A-1'));
  await userEvent.click(screen.getByLabelText('知识库 B-1'));
  await userEvent.type(screen.getByPlaceholderText(/输入检索内容/i), 'test');
  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   // 联查摘要信息
   expect(screen.getByText(/联查 2 个库/)).toBeInTheDocument();
   expect(screen.getByText(/融合方式: rrf/)).toBeInTheDocument();
  });
 });

 /* ═══════════════════════════════════════════
  *  错误态
  * ═══════════════════════════════════════════ */

 it('retrieve 失败时应显示错误提示', async () => {
  mockRetrieve.mockRejectedValue(new Error('Network Error'));
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  await userEvent.click(screen.getByLabelText('知识库 A-1'));
  await userEvent.type(screen.getByPlaceholderText(/输入检索内容/i), 'test');
  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   expect(screen.getByText(/检索失败/i)).toBeInTheDocument();
  });
 });

 it('20013 错误时应显示套餐限制提示', async () => {
  const error = {
   response: {
    data: {
     code: 20013,
     message: '当前套餐最多支持 3 个库联合检索',
    },
   },
  };
  mockRetrieve.mockRejectedValue(error);
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  await userEvent.click(screen.getByLabelText('知识库 A-1'));
  await userEvent.type(screen.getByPlaceholderText(/输入检索内容/i), 'test');
  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   expect(screen.getByText(/当前套餐最多支持 3 个库联合检索/)).toBeInTheDocument();
  });
 });

 /* ═══════════════════════════════════════════
  *  hybrid 条件显示
  * ═══════════════════════════════════════════ */

 it('选择 hybrid 模式应显示 rrf_k 标签', async () => {
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  const customTab = screen.getByRole('tab', { name: /自定义/i });
  await userEvent.click(customTab);

  const hybridTab = screen.getByRole('tab', { name: /hybrid/i });
  await userEvent.click(hybridTab);

  await waitFor(() => {
   expect(screen.getByText(/rrf_k/i)).toBeInTheDocument();
  });
 });
});
