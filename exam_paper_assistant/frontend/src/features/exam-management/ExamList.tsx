import { usePapers, useDeletePaper } from "@/hooks/usePapers";
import { Button } from "@/components/ui/button";
import { Trash2 } from "lucide-react";
import { format } from "date-fns";

export default function ExamList() {
    const { data: papers, isLoading } = usePapers();
    const deletePaper = useDeletePaper();

    if (isLoading) {
        return <div>Loading...</div>;
    }

    return (
        <div className="space-y-6 animate-in fade-in duration-500">
            <div className="flex items-center justify-between">
                <h1 className="text-3xl font-bold tracking-tight">My Exam Papers</h1>
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {papers?.length === 0 ? (
                    <div className="col-span-full text-center text-muted-foreground p-8 border rounded-lg border-dashed">
                        No papers found. Create one to get started.
                    </div>
                ) : (
                    papers?.map((paper) => (
                        <div key={paper.paper_id} className="rounded-xl border bg-card text-card-foreground shadow p-6 flex flex-col justify-between space-y-4">
                            <div>
                                <h3 className="font-semibold text-lg">{paper.paper_name}</h3>
                                <p className="text-sm text-muted-foreground">
                                    Created: {paper.created_at ? format(new Date(paper.created_at), 'PP') : 'Unknown Date'}
                                </p>
                                <div className="mt-2 text-sm bg-secondary inline-block px-2 py-1 rounded">
                                    {paper.question_count} Questions
                                </div>
                            </div>

                            <div className="flex justify-end gap-2 border-t pt-4">
                                <Button variant="destructive" size="icon" onClick={() => deletePaper.mutate(paper.paper_id)}>
                                    <Trash2 className="h-4 w-4" />
                                </Button>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
