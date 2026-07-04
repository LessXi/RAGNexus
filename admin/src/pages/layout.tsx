import { Outlet } from 'react-router-dom';
import AppHeader from '@/components/AppHeader';

/**
 * Layout — 全局布局组件
 *
 * 顶部固定 AppHeader，下方为自适应主内容区。
 * 不再使用侧栏导航。
 */
export default function Layout() {
 return (
  <div className="min-h-screen bg-white">
   <AppHeader />
   <main className="container mx-auto px-4 py-6">
    <Outlet />
   </main>
  </div>
 );
}
