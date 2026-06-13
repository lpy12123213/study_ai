export function PanelEmpty({ children }: { children: string }) {
  return (
    <div className="aurora-insights-empty flex min-h-[180px] items-center justify-center px-4 text-center text-sm text-muted-foreground">
      {children}
    </div>
  )
}
