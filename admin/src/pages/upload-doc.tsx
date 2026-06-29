import { useState, useEffect, useRef, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { getKBs } from '@/utils/storage';
import { preFilterFiles } from '@/utils/file-filter';
import { uploadQueue } from '@/utils/upload-queue';
import type { CachedKB, UploadResultEntry, SkippedFile } from '@/types/api';

/** 检测浏览器是否支持文件夹选择 */
function supportsWebkitDirectory(): boolean {
 return 'webkitdirectory' in HTMLInputElement.prototype;
}

export default function UploadDocPage() {
 const location = useLocation();
 const preselectedKbId = (location.state as { kbId?: string } | null)?.kbId;

 const [kbId, setKbId] = useState(preselectedKbId || '');
 const [manualKbId, setManualKbId] = useState('');
 const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
 const [skippedFiles, setSkippedFiles] = useState<SkippedFile[]>([]);
 const [results, setResults] = useState<UploadResultEntry[] | null>(null);
 const [uploading, setUploading] = useState(false);
 const [progress, setProgress] = useState<string>('');
 const [progressBar, setProgressBar] = useState(0);

 const kbList = getKBs();
 const canWebkitDir = supportsWebkitDirectory();
 const fileInputRef = useRef<HTMLInputElement>(null);
 const folderInputRef = useRef<HTMLInputElement>(null);

 // beforeunload 保护
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
 };

 const successCount = results?.filter((r) => r.status === 'success').length ?? 0;
 const failCount = results?.filter((r) => r.status === 'failed').length ?? 0;

 return (
  <div>
   <h1 className="text-xl font-semibold mb-1">📤 文档上传</h1>
   <p className="text-slate-400 text-sm mb-6">
    向已有知识库上传 Markdown (.md) 或纯文本 (.txt) 文档。支持单文件选择和文件夹批量上传。
   </p>

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
      {kbList.map((kb: CachedKB) => (
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
      accept=".md,.txt"
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
     支持 .md / .txt 格式，单文件不超过 10MB。文件夹上传将逐个顺序上传。
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
      合计 {results.length} 个文件，{successCount} 个成功，{failCount} 个失败
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
          <span
           className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${r.status === 'success'
            ? 'bg-green-600/20 text-green-400'
            : 'bg-red-600/20 text-red-400'
            }`}
          >
           {r.status === 'success' ? '✅ 成功' : '❌ 失败'}
          </span>
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
