import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import UploadDocPage from './upload-doc';

// mock fetchTree / createKB
const mockFetchTree = vi.fn();
const mockCreateKB = vi.fn();

vi.mock('@/services/api', () => ({
  fetchTree: (...args: unknown[]) => mockFetchTree(...args),
  createKB: (...args: unknown[]) => mockCreateKB(...args),
}));

function renderPage(kbId?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const initialEntries = kbId
    ? [{ pathname: '/upload', state: { kbId } }]
    : ['/upload'];
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>
        <UploadDocPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('UploadDocPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchTree.mockResolvedValue([]);
  });

  it('应渲染页面标题和 KB 选择区', async () => {
    renderPage();
    expect(screen.getByText('📤 文档上传')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('① 选择目标知识库')).toBeInTheDocument();
    });
    expect(screen.getByText('② 选择文件')).toBeInTheDocument();
  });

  it('应显示手动输入 KB ID 的输入框', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByPlaceholderText('例如：kb_a1b2c3d4')).toBeInTheDocument();
    });
  });

  it('初始无 KB 时应显示占位提示', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('-- 请选择知识库 --')).toBeInTheDocument();
    });
  });

  it('fetchTree 返回 KB 时应展示在下拉列表中', async () => {
    mockFetchTree.mockResolvedValue([
      {
        tenant_id: 'tenant_x',
        knowledge_bases: [
          { kb_id: 'kb_abc', name: '测试库', description: '', document_count: 0, total_chunks: 0, created_at: '2026-01-01', documents: [] },
        ],
      },
    ]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/测试库/)).toBeInTheDocument();
    });
  });

  it('从路由 state 传入 kbId 时应预选', async () => {
    mockFetchTree.mockResolvedValue([
      {
        tenant_id: 't1',
        knowledge_bases: [
          { kb_id: 'kb_preselected', name: '预选库', description: '', document_count: 0, total_chunks: 0, created_at: '2026-01-01', documents: [] },
        ],
      },
    ]);
    renderPage('kb_preselected');
    await waitFor(() => {
      const select = screen.getByRole('combobox') as HTMLSelectElement;
      expect(select.value).toBe('kb_preselected');
    });
  });

  it('文件选择按钮应存在', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('📎 选择文件')).toBeInTheDocument();
    });
  });

  it('上传进度区在未上传时应不显示', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.queryByText('③ 上传进度')).toBeNull();
    });
  });

  describe('创建知识库 Card', () => {
    it('应渲染创建 KB Card（默认展开）', async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText('🆕 创建知识库')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('例如：tenant_demo')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('例如：产品文档库')).toBeInTheDocument();
        expect(screen.getByText('✨ 创建')).toBeInTheDocument();
      });
    });

    it('表单为空时创建按钮应禁用', async () => {
      renderPage();
      await waitFor(() => {
        const btn = screen.getByText('✨ 创建') as HTMLButtonElement;
        expect(btn.disabled).toBe(true);
      });
    });

    it('填写表单后创建按钮应启用', async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByPlaceholderText('例如：tenant_demo')).toBeInTheDocument();
      });

      const user = userEvent.setup();
      await user.type(screen.getByPlaceholderText('例如：tenant_demo'), 't1');
      await user.type(screen.getByPlaceholderText('例如：产品文档库'), '我的库');

      const btn = screen.getByText('✨ 创建') as HTMLButtonElement;
      expect(btn.disabled).toBe(false);
    });

    it('创建成功后应清空表单并刷新 KB 下拉', async () => {
      mockCreateKB.mockResolvedValue({
        code: 0,
        data: { kb_id: 'kb_new', name: '我的库', tenant_id: 't1', created_at: '2026-01-01' },
        message: 'ok',
      });
      // 初始 fetchTree 返回空
      mockFetchTree.mockResolvedValueOnce([]);
      // 刷新后 fetchTree 返回新 KB
      mockFetchTree.mockResolvedValueOnce([
        {
          tenant_id: 't1',
          knowledge_bases: [
            { kb_id: 'kb_new', name: '我的库', description: '', document_count: 0, total_chunks: 0, created_at: '2026-01-01', documents: [] },
          ],
        },
      ]);

      renderPage();
      const user = userEvent.setup();

      await waitFor(() => {
        expect(screen.getByPlaceholderText('例如：tenant_demo')).toBeInTheDocument();
      });

      await user.type(screen.getByPlaceholderText('例如：tenant_demo'), 't1');
      await user.type(screen.getByPlaceholderText('例如：产品文档库'), '我的库');
      await user.click(screen.getByText('✨ 创建'));

      await waitFor(() => {
        // 表单清空
        expect((screen.getByPlaceholderText('例如：tenant_demo') as HTMLInputElement).value).toBe('');
        expect((screen.getByPlaceholderText('例如：产品文档库') as HTMLInputElement).value).toBe('');
        // toast 出现
        expect(screen.getByText('知识库「我的库」创建成功')).toBeInTheDocument();
        // KB 下拉刷新 — 检查 select 的 option
        const select = screen.getByRole('combobox') as HTMLSelectElement;
        expect(select.options).toHaveLength(2); // 占位 + 新 KB
        expect(select.options[1].textContent).toContain('我的库');
      });
    });
  });

  it('创建失败时应显示错误 toast', async () => {
    mockCreateKB.mockRejectedValue(new Error('fail'));
    mockFetchTree.mockResolvedValue([]);

    renderPage();
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByPlaceholderText('例如：tenant_demo')).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText('例如：tenant_demo'), 't1');
    await user.type(screen.getByPlaceholderText('例如：产品文档库'), 'x');
    await user.click(screen.getByText('✨ 创建'));

    await waitFor(() => {
      expect(screen.getByText('创建失败，请检查输入或稍后重试')).toBeInTheDocument();
    });
  });
});
