import type { CachedKB } from '@/types/api';

const STORAGE_KEY = 'ragnexus_kbs';

/** 从 localStorage 读取已缓存的知识库列表 */
export function getKBs(): CachedKB[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    console.warn('localStorage 数据损坏，已重置知识库缓存');
    localStorage.removeItem(STORAGE_KEY);
    return [];
  }
}

/** 添加知识库到本地缓存，去重后返回完整列表 */
export function addKB(kb: CachedKB): CachedKB[] {
  const list = getKBs();
  if (list.some((item) => item.kb_id === kb.kb_id)) return list;
  list.push(kb);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    console.warn('localStorage 写入失败（可能配额已满），知识库未缓存');
  }
  return list;
}

/** 从本地缓存中移除指定知识库 */
export function removeKB(kb_id: string): void {
  const list = getKBs().filter((item) => item.kb_id !== kb_id);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}
