import { describe, it, expect } from 'vitest';
import { preFilterFiles } from './file-filter';

function makeFile(name: string, size: number): File {
  return new File(['x'.repeat(Math.max(0, size))], name);
}

describe('preFilterFiles', () => {
  it('应将 .md 和 .txt 文件归类为有效', () => {
    const files = [makeFile('doc.md', 1000), makeFile('notes.txt', 500)];
    const result = preFilterFiles(files);
    expect(result.valid).toHaveLength(2);
    expect(result.skipped).toHaveLength(0);
  });

  it('应跳过 0 字节文件', () => {
    const files = [makeFile('empty.md', 0)];
    const result = preFilterFiles(files);
    expect(result.valid).toHaveLength(0);
    expect(result.skipped).toHaveLength(1);
    expect(result.skipped[0].reason).toContain('为空');
  });

  it('应跳过超过 10MB 的文件', () => {
    const files = [makeFile('big.md', 11 * 1024 * 1024)];
    const result = preFilterFiles(files);
    expect(result.valid).toHaveLength(0);
    expect(result.skipped).toHaveLength(1);
    expect(result.skipped[0].reason).toContain('10MB');
  });

  it('应跳过不支持的扩展名', () => {
    const files = [makeFile('doc.pdf', 1000), makeFile('image.png', 500)];
    const result = preFilterFiles(files);
    expect(result.valid).toHaveLength(0);
    expect(result.skipped).toHaveLength(2);
  });

  it('无扩展名文件应预过滤', () => {
    const files = [makeFile('noext', 100)];
    const result = preFilterFiles(files);
    expect(result.valid).toHaveLength(0);
    expect(result.skipped).toHaveLength(1);
    expect(result.skipped[0].reason).toContain('不支持的类型');
  });

  it('应正确混合有效和无效文件', () => {
    const files = [
      makeFile('doc1.md', 5000),
      makeFile('bad.pdf', 2000),
      makeFile('doc2.txt', 3000),
      makeFile('empty.md', 0),
      makeFile('big.md', 20 * 1024 * 1024),
    ];
    const result = preFilterFiles(files);
    expect(result.valid).toHaveLength(2);
    expect(result.skipped).toHaveLength(3);
  });

  it('应接受空数组', () => {
    const result = preFilterFiles([]);
    expect(result.valid).toHaveLength(0);
    expect(result.skipped).toHaveLength(0);
  });
});
