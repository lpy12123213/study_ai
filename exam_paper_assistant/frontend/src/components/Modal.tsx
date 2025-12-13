import { X } from 'lucide-react';
import { ReactNode } from 'react';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

export default function Modal({ isOpen, onClose, title, children }: Props) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="bg-card w-full max-w-2xl rounded-2xl shadow-2xl border border-white/10 flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between p-5 border-b border-white/5">
          <h3 className="text-lg font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="p-2 text-slate-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-5 overflow-y-auto custom-scrollbar">
          {children}
        </div>
      </div>
    </div>
  );
}
