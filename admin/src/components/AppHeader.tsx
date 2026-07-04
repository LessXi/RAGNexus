/**
 * AppHeader — 公共顶部栏组件（白色科技风）
 *
 * 固定在页面顶部，展示品牌名称。
 * 后端管理台，无需导航链接。
 */
export default function AppHeader() {
 return (
  <header className="sticky top-0 z-50 h-[52px] bg-white border-b border-gray-200 flex items-center px-6">
   <span className="text-lg font-semibold text-gray-800">
    RAGNexus 调试控制台
   </span>
  </header>
 );
}
