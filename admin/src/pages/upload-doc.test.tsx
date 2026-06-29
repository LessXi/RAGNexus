import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import UploadDocPage from './upload-doc';

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
    localStorage.clear();
  });

  it('应渲染页面标题和 KB 选择区', () => {
    renderPage();
    expect(screen.getByText('📤 文档上传')).toBeInTheDocument();
    expect(screen.getByText('① 选择目标知识库')).toBeInTheDocument();
    expect(screen.getByText('② 选择文件')).toBeInTheDocument();
  });

  it('应显示手动输入 KB ID 的输入框', () => {
    renderPage();
    expect(screen.getByPlaceholderText('例如：kb_a1b2c3d4')).toBeInTheDocument();
  });

  it('初始无 KB 时应显示占位提示', () => {
    renderPage();
    expect(screen.getByText('-- 请选择知识库 --')).toBeInTheDocument();
  });

  it('从 localStorage 预选 KB 时应展示在下拉列表中', () => {
    localStorage.setItem(
      'ragnexus_kbs',
      JSON.stringify([{ kb_id: 'kb_abc', name: '测试库', created_at: '2026-01-01' }]),
    );
    renderPage();
    expect(screen.getByText(/测试库/)).toBeInTheDocument();
  });

  it('从路由 state 传入 kbId 时应预选', () => {
    localStorage.setItem(
      'ragnexus_kbs',
      JSON.stringify([{ kb_id: 'kb_preselected', name: '预选库', created_at: '2026-01-01' }]),
    );
    renderPage('kb_preselected');
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('kb_preselected');
  });

  it('文件选择按钮应存在', () => {
    renderPage();
    expect(screen.getByText('📎 选择文件')).toBeInTheDocument();
  });

  it('上传进度区在未上传时应不显示', () => {
    renderPage();
    // 进度区只在 uploading=true 时渲染，不使用 queryByText 用 getByText 会抛异常更合适
    expect(screen.queryByText('③ 上传进度')).toBeNull();
  });
});
