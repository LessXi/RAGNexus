import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryProvider } from '@/components/provider/query-provider';
import Layout from '@/pages/layout';
import UploadDocPage from '@/pages/upload-doc';
import KnowledgeFileTreePage from '@/pages/knowledge-file-tree';

/** 检索调试页 placeholder（待 Task 10 替换） */
const RetrievePage = () => (
  <div className="p-8">检索调试页（施工中）</div>
);

export default function App() {
  return (
    <QueryProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<UploadDocPage />} />
            <Route
              path="/knowledge-bases"
              element={<KnowledgeFileTreePage />}
            />
            <Route
              path="/retrieve"
              element={<RetrievePage />}
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryProvider>
  );
}
