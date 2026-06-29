import { describe, it, expect, beforeEach, vi } from 'vitest';
import { getKBs, addKB, removeKB } from './storage';
import type { CachedKB } from '@/types/api';

describe('storage', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  const sample: CachedKB = {
    kb_id: 'kb_test1234',
    name: '测试库',
    created_at: '2026-06-29T10:00:00',
  };

  describe('addKB', () => {
    it('应添加 KB 并返回更新后的列表', () => {
      const list = addKB(sample);
      expect(list).toHaveLength(1);
      expect(list[0].kb_id).toBe('kb_test1234');
    });

    it('应持久化到 localStorage', () => {
      addKB(sample);
      const raw = localStorage.getItem('ragnexus_kbs');
      expect(raw).not.toBeNull();
      const parsed = JSON.parse(raw!);
      expect(parsed).toHaveLength(1);
    });

    it('重复添加不应产生重复条目', () => {
      addKB(sample);
      addKB(sample);
      const list = getKBs();
      expect(list).toHaveLength(1);
    });
  });

  describe('getKBs', () => {
    it('无缓存时返回空数组', () => {
      expect(getKBs()).toEqual([]);
    });

    it('应返回已缓存的 KB 列表', () => {
      addKB(sample);
      expect(getKBs()).toHaveLength(1);
    });

    it('localStorage 损坏时应返回空数组', () => {
      localStorage.setItem('ragnexus_kbs', '{invalid json');
      const consoleSpy = vi.spyOn(console, 'warn').mockImplementation(() => { });
      const list = getKBs();
      expect(list).toEqual([]);
      consoleSpy.mockRestore();
    });
  });

  describe('removeKB', () => {
    it('应移除指定 KB', () => {
      addKB(sample);
      const kb2: CachedKB = { ...sample, kb_id: 'kb_other' };
      addKB(kb2);
      removeKB('kb_test1234');
      const list = getKBs();
      expect(list).toHaveLength(1);
      expect(list[0].kb_id).toBe('kb_other');
    });
  });
});
