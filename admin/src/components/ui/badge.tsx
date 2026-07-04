import { cn } from '@/lib/utils';

interface BadgeProps {
  children: React.ReactNode;
  className?: string;
}

/** 通用 Badge 组件 */
export function Badge({ children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600',
        className,
      )}
    >
      {children}
    </span>
  );
}
