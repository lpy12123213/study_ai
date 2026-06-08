export function PanelEmpty({ children }: { children: string }) {
  return (
    <div className="flex min-h-[180px] items-center justify-center rounded-md border border-dashed border-border bg-accent px-4 text-center text-sm text-muted-foreground">
      {children}
    </div>
  )
}
