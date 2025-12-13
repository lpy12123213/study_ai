import { ReactNode } from 'react';

interface MainLayoutProps {
    sidebar: ReactNode;
    children: ReactNode;
    header: ReactNode;
}

export default function MainLayout({ sidebar, children, header }: MainLayoutProps) {
    return (
        <div className="h-screen flex flex-col bg-background text-slate-200 overflow-hidden selection:bg-primary/30 selection:text-white">
            {/* Background Gradients are handled in index.css on body, but we can add overlay here if needed */}

            {header}

            <div className="flex-1 flex overflow-hidden px-4 pb-4 gap-4">
                {/* Sidebar Container */}
                <aside className="w-80 flex-shrink-0 flex flex-col glass rounded-2xl overflow-hidden shadow-2xl shadow-black/20 transition-all duration-300">
                    {sidebar}
                </aside>

                {/* Main Content Container */}
                <main className="flex-1 flex flex-col glass rounded-2xl overflow-hidden shadow-2xl shadow-black/20 relative">
                    {children}
                </main>
            </div>
        </div>
    );
}
