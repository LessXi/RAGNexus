import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, type NavigateFunction } from 'react-router-dom';
import { fetchTree } from '@/services/api';
import { fetchAuthMe } from '@/services/authService';
import { fetchDocument, deleteDocument, reindexDocument } from '@/services/documentService';
import { fetchKBDetail, updateKB, deleteKB } from '@/services/knowledgeBaseService';
import type { KBItem, DocItem, DocumentDetail, KBDetail, AuthMeData } from '@/types/api';
import { Badge } from '@/components/ui/badge';
import { StatusBadge } from '@/components/StatusBadge';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { EditKnowledgeBaseDialog } from '@/components/EditKnowledgeBaseDialog';
import {
  ChevronRight,
  ChevronDown,
  Copy,
  Upload,
  Search,
  FileText,
  FolderOpen,
  Trash2,
  RotateCw,
  Pencil,
} from 'lucide-react';

/** KB 行组件 */
function KbRow({
  kb,
  navigate,
  onKbChanged,
}: {
  kb: KBItem;
  navigate: NavigateFunction;
  onKbChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [kbDetail, setKbDetail] = useState<KBDetail | null>(null);
  const [deleting, setDeleting] = useState(false);

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

  const handleEditKB = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const detail = await fetchKBDetail(kb.kb_id);
      setKbDetail(detail);
      setShowEditDialog(true);
    } catch {
      // 静默失败
    }
  };

  const handleDeleteKB = (e: React.MouseEvent) => {
    e.stopPropagation();
    setShowDeleteConfirm(true);
  };

  const confirmDeleteKB = async () => {
    setDeleting(true);
    try {
      await deleteKB(kb.kb_id);
      setShowDeleteConfirm(false);
      onKbChanged();
    } catch {
      // 静默失败
    } finally {
      setDeleting(false);
    }
  };

  const handleSaveKB = async (data: { name?: string; description?: string; settings?: Record<string, unknown> }) => {
    await updateKB(kb.kb_id, data);
    setShowEditDialog(false);
    onKbChanged();
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

          {/* 编辑 KB */}
          <button
            title="编辑知识库"
            onClick={handleEditKB}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-amber-50 hover:text-amber-600"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>

          {/* 删除 KB */}
          <button
            title="删除知识库"
            onClick={handleDeleteKB}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* 文档列表 */}
      {expanded && kb.documents.length > 0 && (
        <div className="ml-6 border-l-2 border-slate-100 pl-4">
          {kb.documents.map((doc) => (
            <DocRow key={doc.doc_id} doc={doc} onDocChanged={onKbChanged} />
          ))}
        </div>
      )}

      {/* 编辑 KB 对话框 */}
      {showEditDialog && kbDetail && (
        <EditKnowledgeBaseDialog
          kb={kbDetail}
          onSave={handleSaveKB}
          onClose={() => setShowEditDialog(false)}
        />
      )}

      {/* 删除 KB 确认 */}
      {showDeleteConfirm && (
        <ConfirmDialog
          title="删除知识库"
          message={`确定要删除「${kb.name}」吗？该操作不可撤销，所有文档将被永久删除。`}
          onConfirm={confirmDeleteKB}
          onCancel={() => setShowDeleteConfirm(false)}
          loading={deleting}
          confirmLabel="删除"
          variant="destructive"
        />
      )}
    </div>
  );
}

/** 文档行组件 */
function DocRow({ doc, onDocChanged }: { doc: DocItem; onDocChanged: () => void }) {
  const POLL_INTERVAL = 3000; // 3 秒轮询
  const MAX_POLLS = 60; // 最多 3 分钟

  const [currentStatus, setCurrentStatus] = useState(doc.status);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const pollCountRef = useRef(0);
  const timerRef = useRef<number | null>(null);

  // 轮询 PROCESSING 状态的文档
  useEffect(() => {
    if (currentStatus !== 'processing') return;

    timerRef.current = setInterval(async () => {
      pollCountRef.current += 1;
      try {
        const detail = await fetchDocument(doc.doc_id);
        setCurrentStatus(detail.status);
        if (detail.status !== 'processing') {
          clearInterval(timerRef.current!);
          onDocChanged(); // 刷新列表以更新 chunk_count 等
        }
      } catch {
        // 轮询失败静默重试
      }

      if (pollCountRef.current >= MAX_POLLS) {
        clearInterval(timerRef.current!);
      }
    }, POLL_INTERVAL);

    return () => {
      clearInterval(timerRef.current!);
    };
  }, [doc.doc_id]); // 只在 doc_id 变化时重启轮询

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    setShowDeleteConfirm(true);
  };

  const confirmDelete = async () => {
    setDeleting(true);
    try {
      await deleteDocument(doc.doc_id);
      setShowDeleteConfirm(false);
      onDocChanged();
    } catch {
      // 静默失败
    } finally {
      setDeleting(false);
    }
  };

  const handleRetry = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setReindexing(true);
    try {
      const result = await reindexDocument(doc.doc_id);
      setCurrentStatus(result.status);
      onDocChanged();
    } catch {
      // 静默失败
    } finally {
      setReindexing(false);
    }
  };

  const isProcessing = currentStatus === 'processing';

  return (
    <div
      className="flex items-center gap-2 rounded px-2 py-1.5"
      data-testid={`doc-${doc.doc_id}`}
    >
      <FileText className="h-3.5 w-3.5 flex-shrink-0 text-slate-300" />
      <span className="text-sm text-slate-600">{doc.filename}</span>
      <StatusBadge status={currentStatus} />

      {/* 操作按钮 */}
      <div className="ml-auto flex items-center gap-0.5">
        {/* 重试按钮（仅 FAILED 显示） */}
        {currentStatus === 'failed' && (
          <button
            title="重新索引"
            onClick={handleRetry}
            disabled={reindexing}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-amber-50 hover:text-amber-600 disabled:opacity-50"
          >
            <RotateCw className={`h-3 w-3 ${reindexing ? 'animate-spin' : ''}`} />
          </button>
        )}

        {/* 删除按钮（PROCESSING 时禁用） */}
        <button
          title={isProcessing ? '索引中，无法删除' : '删除文档'}
          onClick={handleDelete}
          disabled={isProcessing}
          className="rounded p-1 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-30"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>

      {/* 删除确认 */}
      {showDeleteConfirm && (
        <ConfirmDialog
          title="删除文档"
          message={`确定要删除「${doc.filename}」吗？该操作不可撤销。`}
          onConfirm={confirmDelete}
          onCancel={() => setShowDeleteConfirm(false)}
          loading={deleting}
          confirmLabel="删除"
          variant="destructive"
        />
      )}
    </div>
  );
}

/** 知识库列表页 */
export default function KnowledgeFileTreePage() {
  const [treeItems, setTreeItems] = useState<KBItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState('');
  const [tenantInfo, setTenantInfo] = useState<AuthMeData | null>(null);
  const timerRef = useRef<number | undefined>(undefined);
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

  const handleKbChanged = useCallback(() => {
    loadTree(keyword || undefined);
  }, [keyword, loadTree]);

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
            <>
              <Badge>
                {tenantInfo.tenant_name} ({tenantInfo.tenant_id})
              </Badge>
              {tenantInfo.plan && (
                <Badge className={
                  tenantInfo.plan === 'free' ? 'bg-slate-100 text-slate-600' :
                    tenantInfo.plan === 'standard' ? 'bg-blue-50 text-blue-700' :
                      'bg-purple-50 text-purple-700'
                }>
                  {tenantInfo.plan}
                </Badge>
              )}
              {tenantInfo.plan && tenantInfo.usage && (
                <Badge className="bg-slate-50 text-slate-500 text-xs">
                  今日检索 {tenantInfo.usage.retrieve_daily_count}/{tenantInfo.limits?.retrieve_daily ?? '?'}
                </Badge>
              )}
            </>
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
              <KbRow key={kb.kb_id} kb={kb} navigate={navigate} onKbChanged={handleKbChanged} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
