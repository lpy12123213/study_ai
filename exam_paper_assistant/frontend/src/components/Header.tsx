import { Sparkles } from 'lucide-react';

interface HeaderProps {
  rightContent?: React.ReactNode;
}

export default function Header({ rightContent }: HeaderProps) {
  return (
    <header className="h-16 flex items-center justify-between px-6 shrink-0 z-10">
      <div className="flex items-center gap-3">
        <div className="p-2 bg-gradient-to-br from-primary to-primary-hover rounded-xl shadow-lg shadow-primary/20">
          <Sparkles className="w-5 h-5 text-white" />
        </div>
        <div>
          <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
            AI 智能组卷助手
            <span className="px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-[10px] text-primary-light font-medium uppercase tracking-wider">
              Beta
            </span>
          </h1>
        </div>
      </div>

      <div className="flex items-center gap-4">
        {rightContent}
      </div>
    </header>
  );
}
