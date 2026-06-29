import { Outlet, NavLink } from 'react-router-dom';

export default function Layout() {
  return (
    <div className="flex h-screen">
      {/* 侧栏 */}
      <aside className="w-56 bg-slate-800 border-r border-slate-700 flex flex-col gap-1 p-4 flex-shrink-0">
        <div className="text-indigo-400 font-bold text-base mb-4">
          ⚡ RAGNexus Admin
        </div>
        <NavLink
          to="/knowledge-bases"
          className={({ isActive }) =>
            `px-3 py-2.5 rounded-lg text-sm transition-colors ${isActive
              ? 'bg-indigo-600 text-white'
              : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
            }`
          }
        >
          📚 知识库管理
        </NavLink>
        <NavLink
          to="/upload"
          className={({ isActive }) =>
            `px-3 py-2.5 rounded-lg text-sm transition-colors ${isActive
              ? 'bg-indigo-600 text-white'
              : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
            }`
          }
        >
          📤 文档上传
        </NavLink>
      </aside>

      {/* 主内容区 */}
      <main className="flex-1 overflow-y-auto p-8">
        <Outlet />
      </main>
    </div>
  );
}
