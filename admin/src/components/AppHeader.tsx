/**
 * AppHeader — 公共顶部栏组件（白色科技风）
 *
 * 固定在页面顶部，展示品牌名称和页面导航。
 */
import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
 { to: "/", label: "首页" },
 { to: "/knowledge-bases", label: "知识库列表" },
 { to: "/retrieve", label: "检索调试" },
];

export default function AppHeader() {
 return (
  <header className="sticky top-0 z-50 h-[52px] bg-white border-b border-gray-200 flex items-center px-6 gap-8">
   <span className="text-lg font-semibold text-gray-800">
    RAGNexus 调试控制台
   </span>
   <nav className="flex items-center gap-1">
    {NAV_ITEMS.map((item) => (
     <NavLink
      key={item.to}
      to={item.to}
      className={({ isActive }) =>
       `px-3 py-1 rounded text-sm font-medium transition-colors ${isActive
        ? "bg-gray-100 text-gray-900"
        : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
       }`
      }
     >
      {item.label}
     </NavLink>
    ))}
   </nav>
  </header>
 );
}
