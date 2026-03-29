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
  success: 'bg-green-600',
  error: 'bg-red-600',
  info: 'bg-gray-800',
};

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`${typeStyles[t.type]} text-white px-4 py-2.5 rounded-lg shadow-lg text-sm max-w-sm animate-fade-in pointer-events-auto`}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
