import { describe, it, expect, vi, beforeEach } from 'vitest';
import { uploadQueue } from './upload-queue';
import * as api from '@/services/api';

vi.mock('@/services/api');

describe('uploadQueue', () => {
  const kbId = 'kb_test';
  const successFile = new File(['content'], 'doc.md', { type: 'text/markdown' });
  const failFile = new File([''], 'bad.pdf');

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.uploadDoc).mockResolvedValue({
      code: 0,
      data: { doc_id: 'doc_abc', kb_id: kbId, chunk_count: 3 },
      message: 'ok',
    });
  });

  it('应顺序上传所有文件并返回结果', async () => {
    const files = [successFile, successFile];
    const onProgress = vi.fn();
    const results = await uploadQueue(kbId, files, onProgress);

    expect(results).toHaveLength(2);
    expect(results[0].status).toBe('success');
    expect(results[1].status).toBe('success');
    expect(api.uploadDoc).toHaveBeenCalledTimes(2);
  });

  it('应隔离单文件失败，不影响后续', async () => {
    vi.mocked(api.uploadDoc)
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValueOnce({
        code: 0,
        data: { doc_id: 'doc_xyz', kb_id: kbId, chunk_count: 1 },
        message: 'ok',
      });

    const files = [failFile, successFile];
    const results = await uploadQueue(kbId, files, vi.fn());
    expect(results[0].status).toBe('failed');
    expect(results[0].detail).toContain('无法连接后端服务');
    expect(results[1].status).toBe('success');
  });

  it('应处理后端非零错误码（如 10302 重复文件）', async () => {
    vi.mocked(api.uploadDoc).mockResolvedValue({
      code: 10302,
      data: null as unknown as { doc_id: string; kb_id: string; chunk_count: number },
      message: '文档已存在',
    });

    const files = [successFile];
    const results = await uploadQueue(kbId, files, vi.fn());

    expect(results[0].status).toBe('failed');
    expect(results[0].detail).toBe('文档已存在');
  });

  it('应在每次文件上传前回调进度', async () => {
    const files = [successFile, successFile];
    const onProgress = vi.fn();
    await uploadQueue(kbId, files, onProgress);

    expect(onProgress).toHaveBeenCalledTimes(3); // 2 files + final
    expect(onProgress).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ current: 2, total: 2, currentFile: 'doc.md' }),
    );
  });

  it('连续 3 次失败且用户确认停止时应中断', async () => {
    vi.mocked(api.uploadDoc).mockRejectedValue(new Error('timeout'));
    const mockConfirm = vi
      .spyOn(window, 'confirm')
      .mockReturnValue(true); // 用户点击「停止」

    const files = [failFile, failFile, failFile, successFile];
    const results = await uploadQueue(kbId, files, vi.fn());

    expect(results).toHaveLength(3); // 第 4 个未上传
    expect(mockConfirm).toHaveBeenCalledTimes(1);

    mockConfirm.mockRestore();
  });

  it('连续 3 次失败但用户选择继续时应继续', async () => {
    vi.mocked(api.uploadDoc).mockRejectedValue(new Error('timeout'));
    const mockConfirm = vi
      .spyOn(window, 'confirm')
      .mockReturnValue(false); // 用户点击「继续」

    const files = [failFile, failFile, failFile, successFile];
    const results = await uploadQueue(kbId, files, vi.fn());

    expect(results).toHaveLength(4); // 全部上传
    // 连续失败 3→4 各触发一次熔断询问
    expect(mockConfirm).toHaveBeenCalledTimes(2);
    mockConfirm.mockRestore();
  });
});
