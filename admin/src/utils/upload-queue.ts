import type { UploadProgressCallback, UploadResultEntry } from '@/types/api';
import { uploadDoc } from '@/services/api';

/** 顺序上传队列：逐个上传文件，per-file 错误隔离，通过回调报告进度 */
export async function uploadQueue(
  kbId: string,
  files: File[],
  onProgress: UploadProgressCallback,
): Promise<UploadResultEntry[]> {
  const results: UploadResultEntry[] = [];
  let successCount = 0;
  let failCount = 0;

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    onProgress({
      current: i + 1,
      total: files.length,
      currentFile: file.name,
      successCount,
      failCount,
    });

    try {
      const res = await uploadDoc(kbId, file);
      if (res.code === 0) {
        successCount++;
        results.push({
          name: file.name,
          size: file.size,
          status: 'success',
          detail: `${res.data.doc_id}, ${res.data.chunk_count} chunks`,
        });
      } else {
        failCount++;
        results.push({
          name: file.name,
          size: file.size,
          status: 'failed',
          detail: res.message || `错误码: ${res.code}`,
        });

        // 熔断：连续 3 次失败时询问用户是否继续
        const recentResults = results.slice(-3);
        if (
          results.length >= 3 &&
          recentResults.every((r) => r.status === 'failed')
        ) {
          const shouldStop = window.confirm(
            `连续 3 个文件上传失败，可能后端异常。是否停止上传？（已成功 ${successCount}，已失败 ${failCount}）`,
          );
          if (shouldStop) break;
        }
      }
    } catch (err: unknown) {
      failCount++;
      const message =
        err instanceof Error ? err.message : '未知错误';
      const detail = /timeout/i.test(message)
        ? '上传超时'
        : /network/i.test(message)
          ? '无法连接后端服务'
          : `网络错误: ${message}`;
      results.push({
        name: file.name,
        size: file.size,
        status: 'failed',
        detail,
      });

      // 熔断：连续 3 次失败时询问用户
      const recentResults = results.slice(-3);
      if (
        results.length >= 3 &&
        recentResults.every((r) => r.status === 'failed')
      ) {
        const shouldStop = window.confirm(
          `连续 3 个文件上传失败，可能后端异常。是否停止上传？（已成功 ${successCount}，已失败 ${failCount}）`,
        );
        if (shouldStop) break;
      }
    }
  }

  // 最终进度回调
  onProgress({
    current: files.length,
    total: files.length,
    currentFile: '',
    successCount,
    failCount,
  });

  return results;
}
