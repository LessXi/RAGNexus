import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryProvider } from '@/components/provider/query-provider';
import Layout from '@/pages/layout';
import CreateKBPage from '@/pages/create-kb';
import UploadDocPage from '@/pages/upload-doc';

export default function App() {
  return (
    <QueryProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/knowledge-bases" replace />} />
            <Route path="/knowledge-bases" element={<CreateKBPage />} />
            <Route path="/upload" element={<UploadDocPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryProvider>
  );
}
