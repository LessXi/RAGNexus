import { useState, useEffect, useRef, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { createKB, fetchTree } from '@/services/api';
import { preFilterFiles } from '@/utils/file-filter';
import { uploadQueue } from '@/utils/upload-queue';
import { fetchDocument } from '@/services/documentService';
import api from '@/lib/axios';
import type { KBItem, UploadResultEntry, SkippedFile } from '@/types/api';

/** KB 下拉选项（扁平化后的条目） */
interface KBOption {
 kb_id: string;
 name: string;
}

/** 检测浏览器是否支持文件夹选择 */
function supportsWebkitDirectory(): boolean {
 return 'webkitdirectory' in HTMLInputElement.prototype;
}

export default function UploadDocPage() {
 const location = useLocation();
 const preselectedKbId = (location.state as { kbId?: string } | null)?.kbId;

 // --- KB 下拉 ---
 const [kbId, setKbId] = useState(preselectedKbId || '');
 const [manualKbId, setManualKbId] = useState('');
 const [kbOptions, setKbOptions] = useState<KBOption[]>([]);

 // --- 创建 KB 表单 ---
 const [createCardExpanded, setCreateCardExpanded] = useState(true);

 const [createName, setCreateName] = useState('');
 const [creating, setCreating] = useState(false);
 const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

 // --- 上传 ---
 const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
 const [skippedFiles, setSkippedFiles] = useState<SkippedFile[]>([]);
 const [results, setResults] = useState<UploadResultEntry[] | null>(null);
 const [uploading, setUploading] = useState(false);
 const [progress, setProgress] = useState<string>('');
 const [progressBar, setProgressBar] = useState(0);

 const canWebkitDir = supportsWebkitDirectory();
 const fileInputRef = useRef<HTMLInputElement>(null);
 const folderInputRef = useRef<HTMLInputElement>(null);

 // --- 加载 KB 列表 ---
 const loadKBs = useCallback(async () => {
  try {
   const trees = await fetchTree();
   const options: KBOption[] = [];
   // 后端已改为单租户响应：data[0].knowledge_bases
   const tenantTree = trees[0];
   if (tenantTree) {
    for (const kb of tenantTree.knowledge_bases) {
     options.push({ kb_id: kb.kb_id, name: kb.name });
    }
   }
   setKbOptions(options);
  } catch {
   setKbOptions([]);
  }
 }, []);

 useEffect(() => {
  loadKBs();
 }, [loadKBs]);

 // --- 20014 配额错误拦截 ---
 useEffect(() => {
  const interceptor = api.interceptors.response.use(
   (response) => {
    if (response.data?.code === 20014) {
     const msg = response.data?.message || '操作超出配额限制，请联系管理员';
     setToast({ message: msg, type: 'error' });
     return Promise.reject(new Error(msg));
    }
    return response;
   },
  );
  return () => {
   api.interceptors.response.eject(interceptor);
  };
 }, []);

 // --- 自动隐藏 toast ---
 useEffect(() => {
  if (!toast) return;
  const timer = setTimeout(() => setToast(null), 3000);
  return () => clearTimeout(timer);
 }, [toast]);

 // --- 创建知识库 ---
 const handleCreateKB = async () => {
  if (!createName.trim()) return;

  setCreating(true);
  try {
   await createKB({ name: createName.trim() });
   setToast({ message: `知识库「${createName.trim()}」创建成功`, type: 'success' });
   setCreateName('');
   await loadKBs();
  } catch {
   setToast({ message: '创建失败，请检查输入或稍后重试', type: 'error' });
  } finally {
   setCreating(false);
  }
 };

 // --- beforeunload 保护 ---
 useEffect(() => {
  if (!uploading) return;
  const handler = (e: BeforeUnloadEvent) => {
   e.preventDefault();
  };
  window.addEventListener('beforeunload', handler);
  return () => window.removeEventListener('beforeunload', handler);
 }, [uploading]);

 const effectiveKbId = kbId || manualKbId;

 const handleFiles = useCallback((fileList: FileList | null) => {
  if (!fileList || fileList.length === 0) return;
  const { valid, skipped } = preFilterFiles(fileList);
  setSelectedFiles((prev) => [...prev, ...valid]);
  setSkippedFiles((prev) => [...prev, ...skipped]);
  setResults(null);
 }, []);

 const removeFile = (index: number) => {
  setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
 };

 const clearFiles = () => {
  setSelectedFiles([]);
  setSkippedFiles([]);
  setResults(null);
  setProgress('');
  setProgressBar(0);
 };

 const startUpload = async () => {
  if (!effectiveKbId || selectedFiles.length === 0) return;
  setUploading(true);
  setResults(null);
  setProgress('准备上传...');
  setProgressBar(0);

  const uploadResults = await uploadQueue(
   effectiveKbId,
   selectedFiles,
   ({ current, total, currentFile, successCount, failCount }) => {
    setProgress(`正在上传第 ${current}/${total} 个文件：${currentFile}`);
    setProgressBar(Math.round((current / total) * 100));
    if (current === total) {
     setProgress(
      `上传完成！合计 ${total} 个文件，${successCount} 成功，${failCount} 失败`,
     );
    }
   },
  );

  setResults(uploadResults);
  setUploading(false);

  // 如果有异步索引的文档，提示用户
  const hasProcessing = uploadResults.some((r) => r.status === 'processing');
  if (hasProcessing) {
   setToast({ message: '已提交，正在后台索引', type: 'success' });
  }
 };

 const successCount = results?.filter((r) => r.status === 'success').length ?? 0;
 const processingCount = results?.filter((r) => r.status === 'processing').length ?? 0;
 const failCount = results?.filter((r) => r.status === 'failed').length ?? 0;

 // 轮询 PROCESSING 文档的状态更新
 useEffect(() => {
  const processingEntries = results?.filter((r) => r.status === 'processing' && r.doc_id) ?? [];
  if (processingEntries.length === 0) return;

  const timer = setInterval(async () => {
   const updated = await Promise.all(
    processingEntries.map(async (entry) => {
     try {
      const doc = await fetchDocument(entry.doc_id!);
      if (doc.status !== 'processing') {
       return {
        ...entry,
        status: doc.status as 'success' | 'failed',
        detail: doc.status === 'success'
         ? `${doc.chunk_count} chunks`
         : (doc.error_message || '索引失败'),
       };
      }
     } catch {
      /* 轮询失败静默重试 */
     }
     return entry;
    }),
   );

   const hasChanged = updated.some((u, i) => u.status !== processingEntries[i].status);
   if (hasChanged) setResults(updated);
  }, 3000);

  return () => clearInterval(timer);
 }, [results]);

 return (
  <div>
   <h1 className="text-xl font-semibold mb-1">📤 文档上传</h1>
   <p className="text-slate-400 text-sm mb-6">
    向已有知识库上传 Markdown (.md)、纯文本 (.txt)、PDF (.pdf) 或 Word (.docx) 文档。支持单文件选择和文件夹批量上传。
   </p>

   {/* Toast 通知 */}
   {toast && (
    <div
     className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium transition-all ${toast.type === 'success'
      ? 'bg-green-600/90 text-white'
      : 'bg-red-600/90 text-white'
      }`}
    >
     {toast.message}
    </div>
   )}

   {/* 创建知识库 Card */}
   <details
    open={createCardExpanded}
    className="bg-slate-800 border border-slate-700 rounded-lg mb-4 group"
    onToggle={(e) => setCreateCardExpanded((e.target as HTMLDetailsElement).open)}
   >
    <summary className="px-5 py-3 cursor-pointer select-none flex items-center gap-2 text-base font-semibold list-none">
     <span className="text-slate-400 text-xs transition-transform group-open:rotate-90">
      ▶
     </span>
     🆕 创建知识库
    </summary>
    <div className="px-5 pb-5 pt-1">
     <p className="text-slate-400 text-xs mb-4">
      新建一个知识库，需要提供知识库名称。
     </p>
     <div className="mb-4">
      <label className="block text-sm text-slate-400 mb-1">
       知识库名称 <span className="text-red-400">*</span>
      </label>
      <input
       value={createName}
       onChange={(e) => setCreateName(e.target.value)}
       placeholder="例如：产品文档库"
       maxLength={64}
       className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm
                          text-slate-200 outline-none focus:border-indigo-500
                          placeholder:text-slate-600"
      />
     </div>
     <button
      onClick={handleCreateKB}
      disabled={creating || !createName.trim()}
      className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500
                       disabled:opacity-50 disabled:cursor-not-allowed
                       rounded-md text-sm font-medium transition-colors"
     >
      {creating ? '创建中...' : '✨ 创建'}
     </button>
    </div>
   </details>

   {/* 步骤 1: 选择 KB */}
   <div className="bg-slate-800 border border-slate-700 rounded-lg p-5 mb-4">
    <h2 className="text-base font-semibold mb-3">① 选择目标知识库</h2>
    <div className="mb-3">
     <label className="block text-sm text-slate-400 mb-1">知识库</label>
     <select
      value={kbId}
      onChange={(e) => setKbId(e.target.value)}
      className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm
                       text-slate-200 outline-none focus:border-indigo-500"
     >
      <option value="">-- 请选择知识库 --</option>
      {kbOptions.map((kb) => (
       <option key={kb.kb_id} value={kb.kb_id}>
        {kb.name} ({kb.kb_id})
       </option>
      ))}
     </select>
    </div>
    <div>
     <label className="block text-sm text-slate-400 mb-1">
      或手动输入 KB ID
     </label>
     <input
      value={manualKbId}
      onChange={(e) => setManualKbId(e.target.value)}
      className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm
                       text-slate-200 font-mono outline-none focus:border-indigo-500"
      placeholder="例如：kb_a1b2c3d4"
     />
    </div>
   </div>

   {/* 步骤 2: 选择文件 */}
   <div className="bg-slate-800 border border-slate-700 rounded-lg p-5 mb-4">
    <h2 className="text-base font-semibold mb-3">② 选择文件</h2>
    <div className="flex gap-2 mb-2">
     <button
      onClick={() => fileInputRef.current?.click()}
      className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-md text-sm
                       font-medium transition-colors"
     >
      📎 选择文件
     </button>
     {canWebkitDir && (
      <button
       onClick={() => folderInputRef.current?.click()}
       className="px-4 py-2 border border-slate-600 hover:border-indigo-500
                         rounded-md text-sm transition-colors"
      >
       📁 选择文件夹
      </button>
     )}
     {!canWebkitDir && (
      <span className="text-xs text-amber-400 self-center">
       当前浏览器不支持文件夹选择，请使用 Chrome 或 Edge
      </span>
     )}
     <input
      ref={fileInputRef}
      type="file"
      multiple
      accept=".md,.txt,.pdf,.docx"
      className="hidden"
      onChange={(e) => handleFiles(e.target.files)}
     />
     <input
      ref={folderInputRef}
      type="file"
      // @ts-expect-error webkitdirectory 非标准属性
      webkitdirectory=""
      className="hidden"
      onChange={(e) => handleFiles(e.target.files)}
     />
    </div>
    <p className="text-slate-500 text-xs">
     支持 .md / .txt / .pdf / .docx 格式，单文件不超过 10MB。文件夹上传将逐个顺序上传。
    </p>

    {/* 已选文件预览 */}
    {selectedFiles.length > 0 && (
     <div className="mt-4">
      <div className="flex items-center justify-between mb-2">
       <p className="text-sm font-medium">
        已选文件（{selectedFiles.length} 个）
        {skippedFiles.length > 0 && (
         <span className="text-amber-400 text-xs ml-2">
          ，已跳过 {skippedFiles.length} 个不支持的文件
         </span>
        )}
       </p>
       {!uploading && (
        <button
         onClick={clearFiles}
         className="text-xs text-slate-400 hover:text-slate-200"
        >
         清空
        </button>
       )}
      </div>

      {/* 被跳过的文件（灰色） */}
      {skippedFiles.length > 0 && (
       <div className="border border-slate-700 rounded-md mb-2 max-h-32 overflow-y-auto">
        {skippedFiles.map((f, i) => (
         <div
          key={`skip-${i}`}
          className="flex justify-between items-center px-3 py-2 border-b
                               border-slate-700/50 last:border-0 text-slate-500 text-sm"
         >
          <span>📄 {f.name}</span>
          <span className="text-xs text-amber-400">{f.reason}</span>
         </div>
        ))}
       </div>
      )}

      {/* 有效文件 */}
      <div className="border border-slate-700 rounded-md max-h-48 overflow-y-auto">
       {selectedFiles.map((file, i) => (
        <div
         key={i}
         className="flex justify-between items-center px-3 py-2 border-b
                             border-slate-700/50 last:border-0 text-sm"
        >
         <div className="flex items-center gap-2">
          <span>📄 {file.name}</span>
          {!uploading && (
           <button
            onClick={() => removeFile(i)}
            className="text-slate-500 hover:text-red-400 text-xs"
           >
            ✕
           </button>
          )}
         </div>
         <span className="text-xs text-slate-400">
          {(file.size / 1024).toFixed(1)} KB
         </span>
        </div>
       ))}
      </div>

      {!uploading && (
       <button
        onClick={startUpload}
        disabled={!effectiveKbId}
        className="mt-3 px-4 py-2 bg-indigo-600 hover:bg-indigo-500
                           disabled:opacity-50 disabled:cursor-not-allowed
                           rounded-md text-sm font-medium transition-colors"
       >
        🚀 开始上传
       </button>
      )}
     </div>
    )}
   </div>

   {/* 步骤 3: 上传进度 */}
   {uploading && (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-5 mb-4">
     <h2 className="text-base font-semibold mb-3">③ 上传进度</h2>
     <p className="text-sm mb-2">{progress}</p>
     <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
      <div
       className="h-full bg-indigo-500 rounded-full transition-all duration-300"
       style={{ width: `${progressBar}%` }}
      />
     </div>
     <p className="text-xs text-slate-400 mt-2">{progressBar}%</p>
    </div>
   )}

   {/* 步骤 4: 上传结果 */}
   {results && !uploading && (
    <div className="bg-slate-800 border border-green-600/30 rounded-lg p-5">
     <h2 className="text-base font-semibold text-green-400 mb-1">
      ✅ 上传完成
     </h2>
     <p className="text-sm text-slate-400 mb-4">
      合计 {results.length} 个文件，{successCount} 个成功，{processingCount} 个索引中，{failCount} 个失败
     </p>
     <table className="w-full text-sm">
      <thead>
       <tr className="text-slate-400 text-left border-b border-slate-700">
        <th className="py-2.5 px-3 font-medium">文件名</th>
        <th className="py-2.5 px-3 font-medium w-24">大小</th>
        <th className="py-2.5 px-3 font-medium w-20">状态</th>
        <th className="py-2.5 px-3 font-medium">详情</th>
       </tr>
      </thead>
      <tbody>
       {results.map((r, i) => (
        <tr key={i} className="border-b border-slate-700/50">
         <td className="py-2.5 px-3">{r.name}</td>
         <td className="py-2.5 px-3 text-slate-400">
          {(r.size / 1024).toFixed(1)} KB
         </td>
         <td className="py-2.5 px-3">
          {r.status === 'success' ? (
           <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-600/20 text-green-400">✅ 成功</span>
          ) : r.status === 'processing' ? (
           <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-600/20 text-amber-400">⏳ 索引中</span>
          ) : (
           <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-600/20 text-red-400">❌ 失败</span>
          )}
         </td>
         <td className="py-2.5 px-3 text-xs text-slate-400">{r.detail}</td>
        </tr>
       ))}
      </tbody>
     </table>
     <div className="flex gap-2 mt-4">
      <button
       onClick={clearFiles}
       className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-md text-sm
                         font-medium transition-colors"
      >
       继续上传
      </button>
      <button
       onClick={() => {
        clearFiles();
        setManualKbId('');
        setKbId('');
       }}
       className="px-4 py-2 border border-slate-600 hover:border-slate-500
                         rounded-md text-sm transition-colors"
      >
       清空重来
      </button>
     </div>
    </div>
   )}
  </div>
 );
}
