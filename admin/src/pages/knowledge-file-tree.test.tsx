import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import KnowledgeFileTreePage from './knowledge-file-tree';

const mockFetchTree = vi.fn();
const mockNavigate = vi.fn();

vi.mock('@/services/api', () => ({
  fetchTree: (...args: unknown[]) => mockFetchTree(...args),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// navigator.clipboard mock — 必须 configurable:true，否则 userEvent 会冲突
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
      <MemoryRouter initialEntries={['/knowledge-bases']}>
        <KnowledgeFileTreePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('KnowledgeFileTreePage', () => {
  beforeEach(() => {
    mockFetchTree.mockReset();
    mockNavigate.mockReset();
    mockWriteText.mockReset();
  });

  // --- 基础渲染 ---

  it('应渲染页面标题和搜索框', () => {
    mockFetchTree.mockResolvedValue([]);
    renderPage();
    expect(screen.getByText('知识库列表')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('搜索租户...')).toBeInTheDocument();
  });

  // --- 加载态 ---

  it('初始应显示加载态', () => {
    mockFetchTree.mockReturnValue(new Promise(() => { })); // 永不 resolve
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

  it('fetchTree 返回数据时应渲染三级树结构', async () => {
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
                status: 'active',
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

    await waitFor(() => {
      expect(screen.getByText('tenant_a')).toBeInTheDocument();
    });

    // 默认折叠，需先展开租户
    await userEvent.click(screen.getByText('tenant_a'));

    // L2: KB 节点
    expect(screen.getByText('My KB')).toBeInTheDocument();
    expect(screen.getByText('kb_1')).toBeInTheDocument();
    expect(screen.getByText('Empty KB')).toBeInTheDocument();

    // L3: 文档节点 — 需先展开 KB
    const myKbRow = screen.getByText('My KB').closest('div')!;
    await userEvent.click(myKbRow);
    expect(screen.getByText('readme.pdf')).toBeInTheDocument();
    expect(screen.getByText('guide.md')).toBeInTheDocument();

    // 统计信息
    expect(screen.getByText(/3 文档/)).toBeInTheDocument();
    expect(screen.getByText(/150 chunks/)).toBeInTheDocument();
    expect(screen.getByText(/0 文档/)).toBeInTheDocument();

    // status 标签
    expect(screen.getByText('active')).toBeInTheDocument();
    expect(screen.getByText('processing')).toBeInTheDocument();
  });

  // --- 展开/折叠 L1 租户 ---

  it('点击租户应展开/折叠其下的 KB 列表', async () => {
    mockFetchTree.mockResolvedValue([
      {
        tenant_id: 'tenant_x',
        knowledge_bases: [
          {
            kb_id: 'kb_a',
            name: 'KB A',
            description: '',
            document_count: 1,
            total_chunks: 10,
            created_at: '2025-01-01T00:00:00Z',
            documents: [],
          },
        ],
      },
    ]);

    renderPage();
    await waitFor(() => {
      expect(screen.getByText('tenant_x')).toBeInTheDocument();
    });

    // 默认折叠：KB 不应可见
    expect(screen.queryByText('KB A')).not.toBeInTheDocument();

    // 点击展开
    const tenantRow = screen.getByText('tenant_x').closest('div')!;
    await userEvent.click(tenantRow);
    expect(screen.getByText('KB A')).toBeInTheDocument();

    // 再次点击折叠
    await userEvent.click(tenantRow);
    expect(screen.queryByText('KB A')).not.toBeInTheDocument();
  });

  // --- 展开/折叠 L2 KB ---

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
                status: 'active',
                uploaded_at: '2025-01-01T00:00:00Z',
              },
            ],
          },
        ],
      },
    ]);

    renderPage();
    await waitFor(() => {
      expect(screen.getByText('tenant_a')).toBeInTheDocument();
    });

    // 先展开租户
    await userEvent.click(screen.getByText('tenant_a'));
    expect(screen.getByText('My KB')).toBeInTheDocument();

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

    const input = screen.getByPlaceholderText('搜索租户...');
    await userEvent.clear(input);
    await userEvent.type(input, 'tenant_x');

    // 等待防抖（约 350ms）
    await waitFor(
      () => {
        expect(mockFetchTree).toHaveBeenCalledWith('tenant_x');
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
      expect(screen.getByText('t1')).toBeInTheDocument();
    });
    await userEvent.click(screen.getByText('t1'));

    // 找到复制按钮（标题为「复制 KB ID」）
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
      expect(screen.getByText('t1')).toBeInTheDocument();
    });
    await userEvent.click(screen.getByText('t1'));

    const uploadBtn = screen.getByTitle('上传文档');
    await userEvent.click(uploadBtn);
    expect(mockNavigate).toHaveBeenCalledWith('/?kb_id=kb_xyz');
  });

  // --- 跳转检索 ---

  it('点击检索按钮应跳转到 /retrieve?tenant_id=xxx&kb_id=yyy', async () => {
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
      expect(screen.getByText('t_alpha')).toBeInTheDocument();
    });
    await userEvent.click(screen.getByText('t_alpha'));

    const retrieveBtn = screen.getByTitle('检索');
    await userEvent.click(retrieveBtn);
    expect(mockNavigate).toHaveBeenCalledWith(
      '/retrieve?tenant_id=t_alpha&kb_id=kb_beta',
    );
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
