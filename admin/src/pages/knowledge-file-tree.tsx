import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchTree, fetchAuthMe } from '@/services/api';
import type { KBItem, DocItem } from '@/types/api';
import { Badge } from '@/components/ui/badge';
import {
  ChevronRight,
  ChevronDown,
  Copy,
  Upload,
  Search,
  FileText,
  FolderOpen,
} from 'lucide-react';

/** KB 行组件 */
function KbRow({
  kb,
  navigate,
}: {
  kb: KBItem;
  navigate: ReturnType<typeof useNavigate>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const toggle = () => setExpanded((v) => !v);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(kb.kb_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 静默失败
    }
  };

  const handleUpload = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate(`/?kb_id=${kb.kb_id}`);
  };

  const handleRetrieve = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate(`/retrieve?kb_id=${kb.kb_id}`);
  };

  return (
    <div className="py-0.5">
      {/* KB 头部 */}
      <div
        className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 transition-colors hover:bg-slate-50"
        onClick={toggle}
        data-testid={`kb-${kb.kb_id}`}
      >
        {kb.documents.length > 0 ? (
          expanded ? (
            <ChevronDown className="h-3.5 w-3.5 flex-shrink-0 text-slate-400" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 flex-shrink-0 text-slate-400" />
          )
        ) : (
          <span className="block h-3.5 w-3.5 flex-shrink-0" />
        )}
        <FolderOpen className="h-3.5 w-3.5 flex-shrink-0 text-amber-500" />
        <span className="text-sm font-medium text-slate-700">{kb.name}</span>

        {/* kb_id badge */}
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-500">
          {kb.kb_id}
        </span>

        {/* 统计 */}
        <span className="ml-auto mr-2 text-xs text-slate-400">
          {kb.document_count} 文档 · {kb.total_chunks} chunks
        </span>

        {/* 操作按钮 */}
        <div className="flex items-center gap-1">
          {/* 复制 */}
          <button
            title="复制 KB ID"
            onClick={handleCopy}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          >
            {copied ? (
              <span className="text-[10px] text-green-600">已复制</span>
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>

          {/* 上传 */}
          <button
            title="上传文档"
            onClick={handleUpload}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-blue-50 hover:text-blue-600"
          >
            <Upload className="h-3.5 w-3.5" />
          </button>

          {/* 检索 */}
          <button
            title="检索"
            onClick={handleRetrieve}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-purple-50 hover:text-purple-600"
          >
            <Search className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* 文档列表 */}
      {expanded && kb.documents.length > 0 && (
        <div className="ml-6 border-l-2 border-slate-100 pl-4">
          {kb.documents.map((doc) => (
            <DocRow key={doc.doc_id} doc={doc} />
          ))}
        </div>
      )}
    </div>
  );
}

/** 文档行组件 */
function DocRow({ doc }: { doc: DocItem }) {
  const statusColor: Record<string, string> = {
    active: 'bg-green-100 text-green-700',
    processing: 'bg-amber-100 text-amber-700',
    failed: 'bg-red-100 text-red-700',
    ready: 'bg-blue-100 text-blue-700',
  };

  const badgeClass = statusColor[doc.status] ?? 'bg-slate-100 text-slate-600';

  return (
    <div className="flex items-center gap-2 rounded px-2 py-1.5" data-testid={`doc-${doc.doc_id}`}>
      <FileText className="h-3.5 w-3.5 flex-shrink-0 text-slate-300" />
      <span className="text-sm text-slate-600">{doc.filename}</span>
      <span className={`ml-auto rounded px-1.5 py-0.5 text-[10px] font-medium ${badgeClass}`}>
        {doc.status}
      </span>
    </div>
  );
}

/** 知识库列表页 */
export default function KnowledgeFileTreePage() {
  const [treeItems, setTreeItems] = useState<KBItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState('');
  const [tenantInfo, setTenantInfo] = useState<{ tenant_id: string; tenant_name: string } | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigate = useNavigate();

  const loadTree = useCallback(async (kw?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchTree(kw || undefined);
      // 后端改为单租户响应：取 data[0].knowledge_bases
      const tenantTree = data[0];
      setTreeItems(tenantTree?.knowledge_bases ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
      setTreeItems(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // 首次加载
  useEffect(() => {
    loadTree();
  }, [loadTree]);

  // 加载租户信息
  useEffect(() => {
    fetchAuthMe()
      .then((data) => setTenantInfo(data))
      .catch(() => {
        // 静默失败：不影响页面主功能
      });
  }, []);

  // 搜索防抖
  const handleKeywordChange = (value: string) => {
    setKeyword(value);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      loadTree(value || undefined);
    }, 350);
  };

  // 组件卸载时清理 timer
  useEffect(() => {
    return () => {
      clearTimeout(timerRef.current);
    };
  }, []);

  const isEmpty = !loading && !error && treeItems !== null && treeItems.length === 0;

  return (
    <div className="mx-auto max-w-4xl">
      {/* 标题 */}
      <div className="mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-slate-900">知识库列表</h1>
          {tenantInfo && (
            <Badge>
              {tenantInfo.tenant_name} ({tenantInfo.tenant_id})
            </Badge>
          )}
        </div>
        <p className="mt-1 text-sm text-slate-500">浏览和管理当前租户下的知识库与文档</p>
      </div>

      {/* 搜索框 */}
      <div className="relative mb-6">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          type="text"
          value={keyword}
          onChange={(e) => handleKeywordChange(e.target.value)}
          placeholder="搜索知识库名称..."
          className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-10 pr-4 text-sm text-slate-700 placeholder:text-slate-400 focus:border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-100"
        />
      </div>

      {/* 内容区 */}
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        {/* 加载态 */}
        {loading && (
          <div className="flex items-center justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-200 border-t-slate-600" />
            <span className="ml-3 text-sm text-slate-500">加载中...</span>
          </div>
        )}

        {/* 错误态 */}
        {error && (
          <div className="flex flex-col items-center justify-center py-16">
            <p className="text-sm text-red-500">加载失败：{error}</p>
            <button
              onClick={() => loadTree(keyword || undefined)}
              className="mt-3 rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-600 transition-colors hover:bg-slate-200"
            >
              重试
            </button>
          </div>
        )}

        {/* 空状态 */}
        {isEmpty && (
          <div className="flex flex-col items-center justify-center py-16">
            <FolderOpen className="mb-3 h-10 w-10 text-slate-300" />
            <p className="text-sm font-medium text-slate-500">暂无知识库</p>
            <p className="mt-1 text-xs text-slate-400">去上传页创建</p>
            <button
              onClick={() => navigate('/')}
              className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white transition-colors hover:bg-slate-800"
            >
              前往上传页
            </button>
          </div>
        )}

        {/* KB 列表 */}
        {!loading && !error && treeItems !== null && treeItems.length > 0 && (
          <div className="space-y-0.5">
            {treeItems.map((kb) => (
              <KbRow key={kb.kb_id} kb={kb} navigate={navigate} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
