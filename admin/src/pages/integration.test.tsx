/**
 * Phase 5 集成测试 — Task 5.9
 * 验证三页导航和 PROCESSING 文档的状态轮询/按钮禁用逻辑
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import KnowledgeFileTreePage from './knowledge-file-tree';

// --- Mocks ---

const mockFetchTree = vi.fn();
const mockFetchAuthMe = vi.fn();
const mockFetchDocument = vi.fn();
const mockDeleteDocument = vi.fn();
const mockReindexDocument = vi.fn();

vi.mock('@/services/api', () => ({
 fetchTree: (...args: unknown[]) => mockFetchTree(...args),
 fetchAuthMe: (...args: unknown[]) => mockFetchAuthMe(...args),
}));

vi.mock('@/services/documentService', () => ({
 fetchDocument: (...args: unknown[]) => mockFetchDocument(...args),
 deleteDocument: (...args: unknown[]) => mockDeleteDocument(...args),
 reindexDocument: (...args: unknown[]) => mockReindexDocument(...args),
}));

vi.mock('@/services/knowledgeBaseService', () => ({
 fetchKBDetail: vi.fn(),
 updateKB: vi.fn(),
 deleteKB: vi.fn(),
}));

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
 const actual = await vi.importActual('react-router-dom');
 return {
  ...(actual as object),
  useNavigate: () => mockNavigate,
 };
});

function renderPage() {
 const qc = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
 });
 return render(
  <QueryClientProvider client={qc}>
   <MemoryRouter>
    <KnowledgeFileTreePage />
   </MemoryRouter>
  </QueryClientProvider>,
 );
}

/** 创建包含一个 PROCESSING 文档的 mock KB 数据 */
function mockTreeWithProcessingDoc() {
 mockFetchTree.mockResolvedValue([
  {
   tenant_id: 't0',
   knowledge_bases: [
    {
     kb_id: 'kb_p1',
     name: 'Processing KB',
     description: '',
     document_count: 2,
     total_chunks: 0,
     created_at: '2025-01-01T00:00:00Z',
     documents: [
      {
       doc_id: 'doc_processing',
       filename: 'indexing.md',
       status: 'processing',
       uploaded_at: '2025-01-01T00:00:00Z',
      },
      {
       doc_id: 'doc_failed',
       filename: 'broken.md',
       status: 'failed',
       uploaded_at: '2025-01-01T00:00:00Z',
      },
     ],
    },
   ],
  },
 ]);
}

describe('Phase 5 Integration', () => {
 beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockFetchTree.mockReset();
  mockFetchAuthMe.mockReset();
  mockFetchDocument.mockReset();
  mockDeleteDocument.mockReset();
  mockReindexDocument.mockReset();
  mockNavigate.mockReset();
  mockFetchAuthMe.mockResolvedValue({ tenant_id: 'test_tenant', tenant_name: 'Test' });
 });

 afterEach(() => {
  vi.useRealTimers();
 });

 // ============================================================
 // Task 5.9.1: 三页导航验证
 // ============================================================

 describe('三页导航', () => {
  it('点击上传按钮应导航到上传页（带 kb_id 参数）', async () => {
   mockFetchTree.mockResolvedValue([
    {
     tenant_id: 't0',
     knowledge_bases: [
      {
       kb_id: 'kb_nav',
       name: 'Nav KB',
       description: '',
       document_count: 0,
       total_chunks: 0,
       created_at: '2025-01-01T00:00:00Z',
       documents: [],
      },
     ],
    },
   ]);

   renderPage();
   await waitFor(() => {
    expect(screen.getByText('Nav KB')).toBeInTheDocument();
   });

   const uploadBtn = screen.getByTitle('上传文档');
   await userEvent.click(uploadBtn);
   expect(mockNavigate).toHaveBeenCalledWith('/?kb_id=kb_nav');
  });

  it('点击检索按钮应导航到检索页（带 kb_id 参数）', async () => {
   mockFetchTree.mockResolvedValue([
    {
     tenant_id: 't0',
     knowledge_bases: [
      {
       kb_id: 'kb_ret',
       name: 'Ret KB',
       description: '',
       document_count: 0,
       total_chunks: 0,
       created_at: '2025-01-01T00:00:00Z',
       documents: [],
      },
     ],
    },
   ]);

   renderPage();
   await waitFor(() => {
    expect(screen.getByText('Ret KB')).toBeInTheDocument();
   });

   const retrieveBtn = screen.getByTitle('检索');
   await userEvent.click(retrieveBtn);
   expect(mockNavigate).toHaveBeenCalledWith('/retrieve?kb_id=kb_ret');
  });

  it('空状态下点击"前往上传页"按钮应导航到根路径', async () => {
   mockFetchTree.mockResolvedValue([]);

   renderPage();
   await waitFor(() => {
    expect(screen.getByText('暂无知识库')).toBeInTheDocument();
   });

   const goBtn = screen.getByText('前往上传页');
   await userEvent.click(goBtn);
   expect(mockNavigate).toHaveBeenCalledWith('/');
  });
 });

 // ============================================================
 // Task 5.9.2: PROCESSING 文档的状态轮询和按钮禁用逻辑
 // ============================================================

 describe('PROCESSING 文档轮询与按钮状态', () => {
  it('PROCESSING 状态的文档应启动轮询并最终更新为 SUCCESS', async () => {
   mockTreeWithProcessingDoc();
   // 三次 mock：processing → processing → success
   mockFetchDocument
    .mockResolvedValueOnce({
     doc_id: 'doc_processing', kb_id: 'kb_p1', filename: 'indexing.md',
     status: 'processing', chunk_count: 0,
    } as unknown)
    .mockResolvedValueOnce({
     doc_id: 'doc_processing', kb_id: 'kb_p1', filename: 'indexing.md',
     status: 'processing', chunk_count: 0,
    } as unknown)
    .mockResolvedValueOnce({
     doc_id: 'doc_processing', kb_id: 'kb_p1', filename: 'indexing.md',
     status: 'success', chunk_count: 5,
    } as unknown);

   renderPage();

   await waitFor(() => {
    expect(screen.getByText('Processing KB')).toBeInTheDocument();
   });
   const kbRow = screen.getByText('Processing KB').closest('div')!;
   await userEvent.click(kbRow);

   await waitFor(() => {
    expect(screen.getByText('索引中')).toBeInTheDocument();
   });

   // 尚未开始轮询
   expect(mockFetchDocument).not.toHaveBeenCalled();

   // 快进 3.5s → 首次 poll
   await act(() => vi.advanceTimersByTimeAsync(3500));
   expect(mockFetchDocument).toHaveBeenCalledTimes(1);

   // 再快进 3.5s → 第二次 poll
   await act(() => vi.advanceTimersByTimeAsync(3500));
   expect(mockFetchDocument).toHaveBeenCalledTimes(2);

   // 再快进 3.5s → 第三次 poll（返回 success）
   await act(() => vi.advanceTimersByTimeAsync(3500));
   expect(mockFetchDocument).toHaveBeenCalledTimes(3);

   await waitFor(() => {
    expect(screen.getByText('已完成')).toBeInTheDocument();
   });
  });

  it('PROCESSING 文档的删除按钮应禁用', async () => {
   mockTreeWithProcessingDoc();

   renderPage();
   await waitFor(() => {
    expect(screen.getByText('Processing KB')).toBeInTheDocument();
   });
   const kbRow = screen.getByText('Processing KB').closest('div')!;
   await userEvent.click(kbRow);

   await waitFor(() => {
    expect(screen.getByText('索引中')).toBeInTheDocument();
   });

   // PROCESSING 文档的删除按钮应 disabled
   // 找到索引中文档行中的删除按钮
   const docRow = screen.getByTestId('doc-doc_processing');
   const deleteBtn = docRow.querySelector('button[title="索引中，无法删除"]');
   expect(deleteBtn).not.toBeNull();
   expect(deleteBtn).toBeDisabled();
  });

  it('FAILED 文档应显示重试按钮且点击触发 reindex', async () => {
   mockTreeWithProcessingDoc();
   mockReindexDocument.mockResolvedValue({
    doc_id: 'doc_failed',
    status: 'processing',
   });

   renderPage();
   await waitFor(() => {
    expect(screen.getByText('Processing KB')).toBeInTheDocument();
   });
   const kbRow = screen.getByText('Processing KB').closest('div')!;
   await userEvent.click(kbRow);

   await waitFor(() => {
    expect(screen.getByText('失败')).toBeInTheDocument();
   });

   // FAILED 文档应有重试按钮
   const retryBtn = screen.getByTitle('重新索引');
   expect(retryBtn).not.toBeNull();
   expect(retryBtn).not.toBeDisabled();

   // 点击重试
   await userEvent.click(retryBtn);
   expect(mockReindexDocument).toHaveBeenCalledWith('doc_failed');
  });

  it('SUCCESS 状态的文档不应显示重试按钮', async () => {
   mockFetchTree.mockResolvedValue([
    {
     tenant_id: 't0',
     knowledge_bases: [
      {
       kb_id: 'kb_ok',
       name: 'OK KB',
       description: '',
       document_count: 1,
       total_chunks: 5,
       created_at: '2025-01-01T00:00:00Z',
       documents: [
        {
         doc_id: 'doc_ok',
         filename: 'done.md',
         status: 'success',
         uploaded_at: '2025-01-01T00:00:00Z',
        },
       ],
      },
     ],
    },
   ]);

   renderPage();
   await waitFor(() => {
    expect(screen.getByText('OK KB')).toBeInTheDocument();
   });
   const kbRow = screen.getByText('OK KB').closest('div')!;
   await userEvent.click(kbRow);

   await waitFor(() => {
    expect(screen.getByText('已完成')).toBeInTheDocument();
   });

   // SUCCESS 不显示重试按钮
   expect(screen.queryByTitle('重新索引')).toBeNull();
  });
 });
});
