// Skeleton loading components

interface SkeletonProps {
  className?: string;
  lines?: number;
}

export function Skeleton({ className = '', lines = 1 }: SkeletonProps) {
  return (
    <div className={`animate-pulse ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="h-4 bg-gray-200 dark:bg-gray-700 rounded mb-2 last:mb-0"
             style={{ width: `${Math.max(40, 100 - i * 15)}%` }} />
      ))}
    </div>
  );
}

export function SkeletonCard({ className = '' }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded-xl border border-gray-200 dark:border-gray-700 p-4 ${className}`}>
      <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4 mb-3" />
      <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-1/2 mb-2" />
      <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-2/3" />
    </div>
  );
}

export function SkeletonTable({ rows = 5, cols = 3, className = '' }: { rows?: number; cols?: number; className?: string }) {
  return (
    <div className={`animate-pulse ${className}`}>
      {Array.from({ length: rows }).map((_, ri) => (
        <div key={ri} className="flex gap-4 py-3 border-b border-gray-100 dark:border-gray-800 last:border-0">
          {Array.from({ length: cols }).map((_, ci) => (
            <div key={ci} className="h-4 bg-gray-200 dark:bg-gray-700 rounded flex-1"
                 style={{ maxWidth: ci === 0 ? '40%' : '20%' }} />
          ))}
        </div>
      ))}
    </div>
  );
}
