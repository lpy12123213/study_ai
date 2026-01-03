import { Outlet } from "react-router-dom";
import { Sidebar } from "@/components/shared/Sidebar";

export default function RootLayout() {
    return (
        <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
            <Sidebar />
            <main className="min-w-0 flex-1 overflow-hidden">
                <Outlet />
            </main>
        </div>
    );
}
