import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { AxiosError } from 'axios';
import { createKB } from '@/services/api';
import { addKB, getKBs } from '@/utils/storage';
import type { CachedKB } from '@/types/api';

const schema = z.object({
 name: z
  .string()
  .trim()
  .min(1, '知识库名称不能为空')
  .max(64, '知识库名称不能超过 64 个字符'),
});

type FormData = z.infer<typeof schema>;

export default function CreateKBPage() {
 const navigate = useNavigate();
 const [result, setResult] = useState<CachedKB | null>(null);
 const [error, setError] = useState<string | null>(null);
 const [kbList, setKbList] = useState<CachedKB[]>(() => getKBs());

 const {
  register,
  handleSubmit,
  formState: { errors, isSubmitting },
  reset,
 } = useForm<FormData>({
  resolver: zodResolver(schema),
 });

 const onSubmit = async (data: FormData) => {
  setError(null);
  setResult(null);
  try {
   const res = await createKB(data.name);
   if (res.code === 0) {
    const kb: CachedKB = {
     kb_id: res.data.kb_id,
     name: res.data.name,
     created_at: res.data.created_at,
    };
    setResult(kb);
    addKB(kb);
    setKbList(getKBs());
    reset();
   } else {
    setError(res.message || `错误码: ${res.code}`);
   }
  } catch (err: unknown) {
   if (err instanceof AxiosError && err.response?.data?.message) {
    setError(err.response.data.message);
   } else if (err instanceof Error && /network/i.test(err.message)) {
    setError('无法连接后端服务 (localhost:8000)，请确认服务已启动');
   } else if (err instanceof Error) {
    setError(err.message);
   } else {
    setError('未知错误');
   }
  }
 };

 const copyKbId = async (kbId: string) => {
  try {
   await navigator.clipboard.writeText(kbId);
  } catch {
   // fallback: 忽略复制失败
  }
 };

 return (
  <div>
   <h1 className="text-xl font-semibold mb-1">📚 知识库管理</h1>
   <p className="text-slate-400 text-sm mb-6">
    创建和管理 RAG 知识库。创建后可前往「文档上传」页面向知识库添加文档。
   </p>

   {/* 创建表单 */}
   <div className="bg-slate-800 border border-slate-700 rounded-lg p-5 mb-4">
    <h2 className="text-base font-semibold mb-3">创建新知识库</h2>
    <form onSubmit={handleSubmit(onSubmit)}>
     <div className="mb-3">
      <label className="block text-sm text-slate-400 mb-1">
       知识库名称
      </label>
      <input
       {...register('name')}
       className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-sm
                         text-slate-200 outline-none focus:border-indigo-500 transition-colors"
       placeholder="例如：技术文档库"
       maxLength={64}
       autoFocus
      />
      {errors.name && (
       <p className="text-red-400 text-xs mt-1">{errors.name.message}</p>
      )}
      <p className="text-slate-500 text-xs mt-1">
       1-64 个字符，名称不可与已有知识库重复
      </p>
     </div>
     <button
      type="submit"
      disabled={isSubmitting}
      className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50
                       rounded-md text-sm font-medium transition-colors"
     >
      {isSubmitting ? '创建中...' : '创建知识库'}
     </button>
    </form>

    {/* 成功结果 */}
    {result && (
     <>
      <hr className="border-slate-700 my-4" />
      <div className="bg-slate-900 border border-slate-700 rounded-md p-4">
       <h4 className="text-sm font-medium text-green-400 mb-2">
        ✅ 创建成功
       </h4>
       <div className="flex items-center gap-2 bg-indigo-600/20 rounded-md px-3 py-2 text-indigo-400 font-mono text-sm">
        <span>{result.kb_id}</span>
        <button
         onClick={() => copyKbId(result.kb_id)}
         className="text-xs text-slate-400 hover:text-slate-200 transition-colors"
         title="复制"
        >
         📋
        </button>
       </div>
       <p className="text-xs text-slate-400 mt-2">
        名称：{result.name} · 创建时间：{new Date(result.created_at).toLocaleString('zh-CN')}
       </p>
      </div>
     </>
    )}

    {/* 错误信息 */}
    {error && (
     <div className="mt-3 p-3 bg-red-600/10 border border-red-600/30 rounded-md">
      <p className="text-red-400 text-sm">{error}</p>
     </div>
    )}
   </div>

   {/* 已有知识库列表 */}
   <div className="bg-slate-800 border border-slate-700 rounded-lg p-5">
    <h2 className="text-base font-semibold mb-3">
     已有知识库{' '}
     <span className="text-xs text-slate-500 font-normal">（本地缓存）</span>
    </h2>
    {kbList.length > 0 ? (
     <table className="w-full text-sm">
      <thead>
       <tr className="text-slate-400 text-left border-b border-slate-700">
        <th className="py-2.5 px-3 font-medium w-40">KB ID</th>
        <th className="py-2.5 px-3 font-medium">名称</th>
        <th className="py-2.5 px-3 font-medium w-44">创建时间</th>
        <th className="py-2.5 px-3 font-medium w-24">操作</th>
       </tr>
      </thead>
      <tbody>
       {kbList.map((kb) => (
        <tr key={kb.kb_id} className="border-b border-slate-700/50 hover:bg-white/5">
         <td className="py-2.5 px-3">
          <code className="text-xs text-indigo-400">{kb.kb_id}</code>
         </td>
         <td className="py-2.5 px-3">{kb.name}</td>
         <td className="py-2.5 px-3 text-slate-400">
          {new Date(kb.created_at).toLocaleString('zh-CN')}
         </td>
         <td className="py-2.5 px-3">
          <button
           onClick={() => navigate('/upload', { state: { kbId: kb.kb_id } })}
           className="px-2.5 py-1 text-xs border border-slate-600 rounded-md
                                 hover:border-indigo-500 hover:text-indigo-400 transition-colors"
          >
           去上传 →
          </button>
         </td>
        </tr>
       ))}
      </tbody>
     </table>
    ) : (
     <p className="text-slate-500 text-sm text-center py-6">
      暂无知识库，创建一个吧
     </p>
    )}
   </div>
  </div>
 );
}
