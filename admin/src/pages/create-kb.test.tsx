import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import CreateKBPage from './create-kb';

vi.mock('@/services/api', () => ({
  createKB: vi.fn(),
}));

import { createKB } from '@/services/api';

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/knowledge-bases']}>
        <CreateKBPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CreateKBPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('应渲染页面标题和表单', () => {
    renderPage();
    expect(screen.getByText('📚 知识库管理')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('例如：技术文档库')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '创建知识库' })).toBeInTheDocument();
  });

  it('空名称提交应显示校验错误', async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '创建知识库' }));
    await waitFor(() => {
      expect(screen.getByText('知识库名称不能为空')).toBeInTheDocument();
    });
  });

  it('超长名称应显示校验错误', async () => {
    renderPage();
    // 用 fireEvent.change 绕过 HTML maxLength 约束，测试 Zod 校验
    const input = screen.getByPlaceholderText('例如：技术文档库');
    fireEvent.change(input, { target: { value: 'a'.repeat(65) } });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '创建知识库' }));
    await waitFor(() => {
      expect(screen.getByText('知识库名称不能超过 64 个字符')).toBeInTheDocument();
    });
  });

  it('创建成功后应展示结果区和列表', async () => {
    vi.mocked(createKB).mockResolvedValue({
      code: 0,
      data: { kb_id: 'kb_test1234', name: '测试库', created_at: '2026-06-29T10:00:00' },
      message: 'ok',
    });

    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('例如：技术文档库'), '测试库');
    await user.click(screen.getByRole('button', { name: '创建知识库' }));

    await waitFor(() => {
      expect(screen.getByText('✅ 创建成功')).toBeInTheDocument();
    });
    // kb_id 和名称出现在结果区和表格两处，用 getAllByText
    expect(screen.getAllByText('kb_test1234').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('测试库', { exact: false }).length).toBeGreaterThanOrEqual(2);
  });

  it('后端返回错误码应展示错误信息', async () => {
    vi.mocked(createKB).mockResolvedValue({
      code: 10301,
      data: null as unknown as { kb_id: string; name: string; created_at: string },
      message: '知识库名称已存在',
    });

    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('例如：技术文档库'), '重复名称');
    await user.click(screen.getByRole('button', { name: '创建知识库' }));

    await waitFor(() => {
      expect(screen.getByText('知识库名称已存在')).toBeInTheDocument();
    });
  });

  it('网络错误应展示连接失败提示', async () => {
    vi.mocked(createKB).mockRejectedValue(new Error('Network Error'));

    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('例如：技术文档库'), '测试库');
    await user.click(screen.getByRole('button', { name: '创建知识库' }));

    await waitFor(() => {
      expect(screen.getByText(/无法连接后端服务/)).toBeInTheDocument();
    });
  });

  it('创建成功后列表出现新 KB', async () => {
    vi.mocked(createKB).mockResolvedValue({
      code: 0,
      data: { kb_id: 'kb_new', name: '新库', created_at: '2026-06-29T10:00:00' },
      message: 'ok',
    });

    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('例如：技术文档库'), '新库');
    await user.click(screen.getByRole('button', { name: '创建知识库' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '去上传 →' })).toBeInTheDocument();
    });
    expect(screen.getAllByText('kb_new').length).toBeGreaterThanOrEqual(2);
  });

  it('应在提交时禁用按钮防止重复提交', async () => {
    vi.mocked(createKB).mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({
        code: 0,
        data: { kb_id: 'kb_x', name: 'x', created_at: '2026-01-01T00:00:00' },
        message: 'ok',
      }), 100)),
    );

    renderPage();
    const user = userEvent.setup();
    const input = screen.getByPlaceholderText('例如：技术文档库');
    await user.type(input, 'x');
    await user.click(screen.getByRole('button', { name: '创建知识库' }));

    expect(screen.getByRole('button', { name: '创建中...' })).toBeDisabled();
  });
});
