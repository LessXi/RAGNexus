import type { SkippedFile } from '@/types/api';

const ALLOWED_EXTS = ['.md', '.txt'];
const MAX_SIZE = 10 * 1024 * 1024; // 10MB

export interface FilterResult {
  valid: File[];
  skipped: SkippedFile[];
}

/** 客户端预过滤：按扩展名、大小、空文件过滤，减少无效网络请求 */
export function preFilterFiles(files: File[] | FileList): FilterResult {
  const valid: File[] = [];
  const skipped: SkippedFile[] = [];

  for (const file of files) {
    if (file.size === 0) {
      skipped.push({ name: file.name, size: 0, reason: '文件为空' });
      continue;
    }
    if (file.size > MAX_SIZE) {
      skipped.push({ name: file.name, size: file.size, reason: '超过 10MB 限制' });
      continue;
    }
    const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
    if (!ALLOWED_EXTS.includes(ext)) {
      skipped.push({
        name: file.name,
        size: file.size,
        reason: `不支持的类型 (${ext || '无扩展名'})`,
      });
      continue;
    }
    valid.push(file);
  }

  return { valid, skipped };
}
