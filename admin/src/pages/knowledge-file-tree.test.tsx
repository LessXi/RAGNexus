import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import KnowledgeFileTreePage from './knowledge-file-tree';

const mockFetchTree = vi.fn();
const mockFetchAuthMe = vi.fn();
const mockNavigate = vi.fn();

vi.mock('@/services/api', () => ({
  fetchTree: (...args: unknown[]) => mockFetchTree(...args),
}));

vi.mock('@/services/authService', () => ({
  fetchAuthMe: (...args: unknown[]) => mockFetchAuthMe(...args),
}));

// 静默 documentService 和 knowledgeBaseService 的导入（不需要 mock 其方法）
vi.mock('@/services/documentService', () => ({
  fetchDocument: vi.fn(),
  deleteDocument: vi.fn(),
  reindexDocument: vi.fn(),
}));

vi.mock('@/services/knowledgeBaseService', () => ({
  fetchKBDetail: vi.fn(),
  updateKB: vi.fn(),
  deleteKB: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...(actual as object),
    useNavigate: () => mockNavigate,
  };
});

// navigator.clipboard mock
const mockWriteText = vi.fn();
Object.defineProperty(navigator, 'clipboard', {
  value: { writeText: mockWriteText },
  writable: true,
  configurable: true,
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

describe('KnowledgeFileTreePage', () => {
  beforeEach(() => {
    mockFetchTree.mockReset();
    mockFetchAuthMe.mockReset();
    mockNavigate.mockReset();
    mockWriteText.mockReset();
    mockFetchAuthMe.mockResolvedValue({ tenant_id: 'test_tenant', tenant_name: 'Test' });
  });

  // --- 基础渲染 ---

  it('应渲染页面标题和搜索框', () => {
    mockFetchTree.mockResolvedValue([]);
    renderPage();
    expect(screen.getByText('知识库列表')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('搜索知识库名称...')).toBeInTheDocument();
  });

  // --- 加载态 ---

  it('初始应显示加载态', () => {
    mockFetchTree.mockReturnValue(new Promise(() => { }));
    renderPage();
    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  // --- 空状态 ---

  it('fetchTree 返回空数组时应显示空状态', async () => {
    mockFetchTree.mockResolvedValue([]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('暂无知识库')).toBeInTheDocument();
    });
    expect(screen.getByText('去上传页创建')).toBeInTheDocument();
  });

  // --- 树渲染 ---

  it('fetchTree 返回数据时应渲染 KB 和文档', async () => {
    mockFetchTree.mockResolvedValue([
      {
        tenant_id: 'tenant_a',
        knowledge_bases: [
          {
            kb_id: 'kb_1',
            name: 'My KB',
            description: '测试知识库',
            document_count: 3,
            total_chunks: 150,
            created_at: '2025-01-01T00:00:00Z',
            documents: [
              {
                doc_id: 'doc_1',
                filename: 'readme.pdf',
                status: 'success',
                uploaded_at: '2025-01-01T00:00:00Z',
              },
              {
                doc_id: 'doc_2',
                filename: 'guide.md',
                status: 'processing',
                uploaded_at: '2025-01-02T00:00:00Z',
              },
            ],
          },
          {
            kb_id: 'kb_2',
            name: 'Empty KB',
            description: '',
            document_count: 0,
            total_chunks: 0,
            created_at: '2025-01-03T00:00:00Z',
            documents: [],
          },
        ],
      },
    ]);

    renderPage();

    // KB 节点直接可见（2级树）
    await waitFor(() => {
      expect(screen.getByText('My KB')).toBeInTheDocument();
    });
    expect(screen.getByText('kb_1')).toBeInTheDocument();
    expect(screen.getByText('Empty KB')).toBeInTheDocument();

    // 文档节点 — 需先展开 KB
    const myKbRow = screen.getByText('My KB').closest('div')!;
    await userEvent.click(myKbRow);
    expect(screen.getByText('readme.pdf')).toBeInTheDocument();
    expect(screen.getByText('guide.md')).toBeInTheDocument();

    // 统计信息
    expect(screen.getByText(/3 文档/)).toBeInTheDocument();
    expect(screen.getByText(/150 chunks/)).toBeInTheDocument();
    expect(screen.getByText(/0 文档/)).toBeInTheDocument();

    // StatusBadge 渲染中文标签
    expect(screen.getByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('索引中')).toBeInTheDocument();
  });

  // --- 展开/折叠 KB ---

  it('点击 KB 应展开/折叠其下的文档列表', async () => {
    mockFetchTree.mockResolvedValue([
      {
        tenant_id: 'tenant_a',
        knowledge_bases: [
          {
            kb_id: 'kb_1',
            name: 'My KB',
            description: '',
            document_count: 1,
            total_chunks: 5,
            created_at: '2025-01-01T00:00:00Z',
            documents: [
              {
                doc_id: 'doc_1',
                filename: 'secret.txt',
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
      expect(screen.getByText('My KB')).toBeInTheDocument();
    });

    // 默认文档折叠
    expect(screen.queryByText('secret.txt')).not.toBeInTheDocument();

    // 点击 KB 展开文档
    const kbRow = screen.getByText('My KB').closest('div')!;
    await userEvent.click(kbRow);
    expect(screen.getByText('secret.txt')).toBeInTheDocument();

    // 再次点击折叠
    await userEvent.click(kbRow);
    expect(screen.queryByText('secret.txt')).not.toBeInTheDocument();
  });

  // --- 搜索过滤 ---

  it('输入关键词后应调用 fetchTree(keyword)', async () => {
    mockFetchTree.mockResolvedValue([]);
    renderPage();

    await waitFor(() => {
      expect(mockFetchTree).toHaveBeenCalledWith(undefined);
    });

    const input = screen.getByPlaceholderText('搜索知识库名称...');
    await userEvent.clear(input);
    await userEvent.type(input, 'MyKB');

    await waitFor(
      () => {
        expect(mockFetchTree).toHaveBeenCalledWith('MyKB');
      },
      { timeout: 2000 },
    );
  });

  // --- 复制 kb_id ---

  it('点击复制按钮应复制 kb_id 并显示 toast', async () => {
    mockWriteText.mockResolvedValue(undefined);
    mockFetchTree.mockResolvedValue([
      {
        tenant_id: 't1',
        knowledge_bases: [
          {
            kb_id: 'kb_abc123',
            name: 'Test KB',
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
      expect(screen.getByText('Test KB')).toBeInTheDocument();
    });

    const copyBtn = screen.getByTitle('复制 KB ID');
    await userEvent.click(copyBtn);

    expect(mockWriteText).toHaveBeenCalledWith('kb_abc123');
    await waitFor(() => {
      expect(screen.getByText('已复制')).toBeInTheDocument();
    });
  });

  // --- 跳转上传 ---

  it('点击上传按钮应跳转到 /?kb_id=xxx', async () => {
    mockFetchTree.mockResolvedValue([
      {
        tenant_id: 't1',
        knowledge_bases: [
          {
            kb_id: 'kb_xyz',
            name: 'Upload KB',
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
      expect(screen.getByText('Upload KB')).toBeInTheDocument();
    });

    const uploadBtn = screen.getByTitle('上传文档');
    await userEvent.click(uploadBtn);
    expect(mockNavigate).toHaveBeenCalledWith('/?kb_id=kb_xyz');
  });

  // --- 跳转检索 ---

  it('点击检索按钮应跳转到 /retrieve?kb_id=yyy', async () => {
    mockFetchTree.mockResolvedValue([
      {
        tenant_id: 't_alpha',
        knowledge_bases: [
          {
            kb_id: 'kb_beta',
            name: 'Retrieve KB',
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
      expect(screen.getByText('Retrieve KB')).toBeInTheDocument();
    });

    const retrieveBtn = screen.getByTitle('检索');
    await userEvent.click(retrieveBtn);
    expect(mockNavigate).toHaveBeenCalledWith('/retrieve?kb_id=kb_beta');
  });

  // --- 错误态 ---

  it('fetchTree 失败时应显示错误信息', async () => {
    mockFetchTree.mockRejectedValue(new Error('Network Error'));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/加载失败/)).toBeInTheDocument();
    });
  });
});
