import { create } from 'zustand';

interface ToastItem {
  id: number;
  message: string;
  type: 'success' | 'error' | 'info';
}

interface ToastStore {
  toasts: ToastItem[];
  add: (message: string, type?: 'success' | 'error' | 'info') => void;
  remove: (id: number) => void;
}

let _nextId = 0;

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  add: (message, type = 'info') => {
    const id = ++_nextId;
    set((s) => ({ toasts: [...s.toasts, { id, message, type }] }));
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 3500);
  },
  remove: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export function showToast(message: string, type: 'success' | 'error' | 'info' = 'info') {
  useToastStore.getState().add(message, type);
}

const typeStyles = {
  success: 'border-emerald-500/20 bg-[#0f172a] text-white',
  error: 'border-red-500/20 bg-[#1f1113] text-white',
  info: 'border-border/70 bg-popover text-foreground',
};

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  if (!toasts.length) return null;
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[9999] flex flex-col gap-2" role="alert" aria-live="assertive">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`${typeStyles[t.type]} pointer-events-auto max-w-sm rounded-2xl border px-4 py-3 text-sm shadow-[0_28px_70px_-36px_rgba(15,23,42,0.45)] backdrop-blur-xl animate-fade-in`}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
