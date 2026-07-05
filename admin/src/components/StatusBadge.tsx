import { Loader2, Check, X } from 'lucide-react';
import { DocStatus } from '@/types/api';

interface StatusBadgeProps {
  status: string;
  className?: string;
}

/** 文档状态徽标：PROCESSING=黄色旋转、SUCCESS=绿色对勾、FAILED=红色叉号 */
export function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const config: Record<string, { icon: React.ReactNode; cls: string; label: string }> = {
    [DocStatus.PROCESSING]: {
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
      cls: 'bg-amber-100 text-amber-700 border-amber-200',
      label: '索引中',
    },
    [DocStatus.SUCCESS]: {
      icon: <Check className="h-3 w-3" />,
      cls: 'bg-green-100 text-green-700 border-green-200',
      label: '已完成',
    },
    [DocStatus.FAILED]: {
      icon: <X className="h-3 w-3" />,
      cls: 'bg-red-100 text-red-700 border-red-200',
      label: '失败',
    },
  };

  const fallback = {
    icon: null,
    cls: 'bg-slate-100 text-slate-600 border-slate-200',
    label: status,
  };

  const { icon, cls, label } = config[status] ?? fallback;

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${cls} ${className}`}
      data-testid={`status-${status}`}
    >
      {icon}
      {label}
    </span>
  );
}
