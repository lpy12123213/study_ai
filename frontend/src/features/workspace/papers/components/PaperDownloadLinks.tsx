import { Link2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import type { PaperDownloadLink } from '@/api/papers'

export interface PaperDownloadLinksProps {
  download: PaperDownloadLink
}

export function PaperDownloadLinks({ download }: PaperDownloadLinksProps) {
  return (
    <>
      <Separator className="my-8" />
      <Card className="print:border-0 print:shadow-none bg-muted/30">
        <CardContent className="p-6">
          <div className="font-semibold mb-4 flex items-center gap-2">
            <Link2 className="h-4 w-4" />
            查看链接
          </div>

          {!!download.instructions?.length && (
            <ol className="list-decimal pl-5 space-y-1 text-sm text-muted-foreground mb-4">
              {download.instructions.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ol>
          )}

          {download.questionLinks?.length ? (
            <div className="grid gap-2">
              {download.questionLinks.map((url, i) => (
                <a
                  key={`${url}-${i}`}
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-primary hover:underline break-all block p-2 rounded hover:bg-background transition-colors"
                >
                  {i + 1}. {url}
                </a>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              暂无链接
            </div>
          )}
        </CardContent>
      </Card>
    </>
  )
}
