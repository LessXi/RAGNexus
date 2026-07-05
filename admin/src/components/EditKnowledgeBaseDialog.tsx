import { useState } from 'react';
import { Button } from '@/components/ui/button';
import type { KBDetail, UpdateKBRequest } from '@/types/api';

interface EditKnowledgeBaseDialogProps {
  kb: KBDetail;
  onSave: (data: UpdateKBRequest) => Promise<void>;
  onClose: () => void;
}

/** 编辑知识库对话框：name + description + settings (JSON) */
export function EditKnowledgeBaseDialog({
  kb,
  onSave,
  onClose,
}: EditKnowledgeBaseDialogProps) {
  const [name, setName] = useState(kb.name);
  const [description, setDescription] = useState(kb.description ?? '');
  const [settingsJson, setSettingsJson] = useState(
    JSON.stringify(kb.settings ?? {}, null, 2),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setError(null);

    // 校验 settings 是合法 JSON
    let parsedSettings: Record<string, unknown>;
    try {
      parsedSettings = JSON.parse(settingsJson);
    } catch {
      setError('settings 不是合法的 JSON');
      return;
    }

    setSaving(true);
    try {
      await onSave({
        name: name || undefined,
        description: description || undefined,
        settings: parsedSettings,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="edit-kb-dialog-overlay"
    >
      {/* 遮罩 */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={saving ? undefined : onClose}
      />

      {/* 对话框 */}
      <div className="relative z-10 w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-base font-semibold text-slate-900">编辑知识库</h3>

        <div className="mt-4 space-y-3">
          {/* 名称 */}
          <div>
            <label className="block text-xs font-medium text-slate-700">
              名称
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 focus:border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-100"
            />
          </div>

          {/* 描述 */}
          <div>
            <label className="block text-xs font-medium text-slate-700">
              描述
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 focus:border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-100"
            />
          </div>

          {/* settings JSON */}
          <div>
            <label className="block text-xs font-medium text-slate-700">
              Settings (JSON)
            </label>
            <textarea
              value={settingsJson}
              onChange={(e) => setSettingsJson(e.target.value)}
              rows={6}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-1.5 font-mono text-xs text-slate-700 focus:border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-100"
            />
          </div>
        </div>

        {/* 错误提示 */}
        {error && (
          <p className="mt-3 text-xs text-red-500">{error}</p>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onClose}
            disabled={saving}
          >
            取消
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? '保存中...' : '保存'}
          </Button>
        </div>
      </div>
    </div>
  );
}
