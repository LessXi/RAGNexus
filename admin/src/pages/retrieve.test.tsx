import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
function mockRetrieveSuccess() {
 return {
  code: 0,
  data: {
   hits: [
    {
     chunk_id: 'chunk-1',
     kb_id: 'kb_1',
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
   },
  },
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
  *  URL query params 预填
  * ═══════════════════════════════════════════ */

 it('URL 带 ?kb_id=yyy 时应预填 KB 选择框', async () => {
  const sp = new URLSearchParams('?kb_id=kb_2');
  renderPage(sp);

  // 租户由 API Key 自动识别，页面只有 KB 选择器
  const kbSelect = screen.getByLabelText(/知识库/i);
  await waitFor(() => {
   expect((kbSelect as HTMLSelectElement).value).toBe('kb_2');
  });
 });

 /* ═══════════════════════════════════════════
  *  表单校验
  * ═══════════════════════════════════════════ */

 it('未选 KB 时检索按钮应 disabled', async () => {
  renderPage();
  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  expect(getRetrieveButton()).toBeDisabled();
 });

 it('未输入 query 时检索按钮应 disabled', async () => {
  renderPage();
  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  const kbSelect = screen.getByLabelText(/知识库/i);
  await userEvent.selectOptions(kbSelect, 'kb_1');

  expect(getRetrieveButton()).toBeDisabled();
 });

 /* ═══════════════════════════════════════════
  *  检索执行
  * ═══════════════════════════════════════════ */

 it('填写 query 并选 KB 后点击检索按钮应调用 retrieve API', async () => {
  mockRetrieve.mockResolvedValue(mockRetrieveSuccess());
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  const kbSelect = screen.getByLabelText(/知识库/i);
  await userEvent.selectOptions(kbSelect, 'kb_1');

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

 /* ═══════════════════════════════════════════
  *  结果显示
  * ═══════════════════════════════════════════ */

 it('检索成功后应显示 hit 列表', async () => {
  mockRetrieve.mockResolvedValue(mockRetrieveSuccess());
  renderPage();

  await waitFor(() => {
   expect(mockFetchTree).toHaveBeenCalled();
  });

  const kbSelect = screen.getByLabelText(/知识库/i);
  await userEvent.selectOptions(kbSelect, 'kb_1');

  const queryInput = screen.getByPlaceholderText(/输入检索内容/i);
  await userEvent.type(queryInput, 'test query');

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

  const kbSelect = screen.getByLabelText(/知识库/i);
  await userEvent.selectOptions(kbSelect, 'kb_1');

  const queryInput = screen.getByPlaceholderText(/输入检索内容/i);
  await userEvent.type(queryInput, 'test');

  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   expect(screen.getByText('2')).toBeInTheDocument(); // total
   expect(screen.getByText(/45\.2/)).toBeInTheDocument(); // latency
   // mode 同时出现在 tab 和 meta grid，使用 getAllByText
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

  const kbSelect = screen.getByLabelText(/知识库/i);
  await userEvent.selectOptions(kbSelect, 'kb_1');
  await userEvent.type(screen.getByPlaceholderText(/输入检索内容/i), 'test');
  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   // chunk-1 有 score 和 vector_score（formatted to 4 decimal places）
   expect(screen.getByText(/^score: 0\.9500$/)).toBeInTheDocument();
   expect(screen.getByText(/^vec: 0\.9200$/)).toBeInTheDocument();
   // chunk-2 的 score 和 bm25_score 值相同(0.78)，需要含前缀区分
   expect(screen.getByText(/^score: 0\.7800$/)).toBeInTheDocument();
   expect(screen.getByText(/^bm25: 0\.7800$/)).toBeInTheDocument();
   expect(screen.getByText(/^rerank: 0\.8100$/)).toBeInTheDocument();
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

  const kbSelect = screen.getByLabelText(/知识库/i);
  await userEvent.selectOptions(kbSelect, 'kb_1');
  await userEvent.type(screen.getByPlaceholderText(/输入检索内容/i), 'test');
  await userEvent.click(getRetrieveButton());

  await waitFor(() => {
   expect(screen.getByText(/检索失败/i)).toBeInTheDocument();
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

  // 先切换到 custom 简档以显示高级参数
  const customTab = screen.getByRole('tab', { name: /自定义/i });
  await userEvent.click(customTab);

  const hybridTab = screen.getByRole('tab', { name: /hybrid/i });
  await userEvent.click(hybridTab);

  await waitFor(() => {
   expect(screen.getByText(/rrf_k/i)).toBeInTheDocument();
  });
 });
});
