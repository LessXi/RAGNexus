import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryProvider } from '@/components/provider/query-provider';
import Layout from '@/pages/layout';
import UploadDocPage from '@/pages/upload-doc';
import KnowledgeFileTreePage from '@/pages/knowledge-file-tree';
import RetrievePage from '@/pages/retrieve';

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
