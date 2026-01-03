import { Button } from "@/components/ui/button";
import { Link } from "react-router-dom";
import { usePapers } from "@/hooks/usePapers";

export default function Dashboard() {
    const { data: papers, isLoading } = usePapers();
    const totalPapers = papers?.length || 0;
    // Mock questions count for now as API doesn't return it directly globally
    // Assuming papers have a question_count property based on types
    const totalQuestions = papers?.reduce((acc, paper) => acc + (paper.question_count || 0), 0) || 0;

    return (
        <div className="space-y-6 animate-in fade-in duration-500">
            <div className="flex flex-col space-y-2">
                <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
                <p className="text-muted-foreground">
                    Welcome back! Here's an overview of your activity.
                </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {/* Real Stats */}
                <div className="rounded-xl border bg-card text-card-foreground shadow p-6">
                    <div className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <h3 className="tracking-tight text-sm font-medium">Total Papers</h3>
                        <span className="text-muted-foreground">📄</span>
                    </div>
                    <div className="text-2xl font-bold">
                        {isLoading ? "..." : totalPapers}
                    </div>
                    <p className="text-xs text-muted-foreground">Saved locally</p>
                </div>

                <div className="rounded-xl border bg-card text-card-foreground shadow p-6">
                    <div className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <h3 className="tracking-tight text-sm font-medium">Questions</h3>
                        <span className="text-muted-foreground">❓</span>
                    </div>
                    <div className="text-2xl font-bold">
                        {isLoading ? "..." : totalQuestions}
                    </div>
                    <p className="text-xs text-muted-foreground">Across all papers</p>
                </div>
            </div>

            <div className="py-6">
                <div className="flex items-center justify-between space-y-2">
                    <h2 className="text-2xl font-bold tracking-tight">Quick Actions</h2>
                </div>
                <div className="mt-4 flex gap-4">
                    <Link to="/generate">
                        <Button size="lg" className="w-full sm:w-auto">
                            Create New Paper
                        </Button>
                    </Link>
                    <Link to="/exams">
                        <Button variant="outline" size="lg" className="w-full sm:w-auto">
                            View All Papers
                        </Button>
                    </Link>
                </div>
            </div>
        </div>
    );
}
