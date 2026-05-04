import { type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { getRouteCrumbs, matchRouteConfig } from '@/router/routes.config'
import { cn } from '@/lib/utils'
import { useI18n } from '@/i18n'

type SubHeaderProps = {
  actionsSlot?: ReactNode
}

export function SubHeader({ actionsSlot }: SubHeaderProps) {
  const location = useLocation()
  const { routeLabel, t } = useI18n()
  const routeConfig = matchRouteConfig(location.pathname)
  const crumbs = getRouteCrumbs(location.pathname)

  return (
    <div className="flex min-h-11 items-center justify-between gap-4 border-b border-border bg-background px-4 lg:px-6">
      <div className="min-w-0">
        <nav aria-label={t('layout.breadcrumbs')} className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
          {crumbs.map((crumb, index) => {
            const label = routeLabel(crumb.id, crumb.label)
            return (
              <span key={crumb.id} className="flex min-w-0 items-center gap-1">
                {index > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />}
                {crumb.current ? (
                  <span className="truncate font-medium text-foreground">{label}</span>
                ) : (
                  <Link
                    to={crumb.path}
                    className={cn(
                      'truncate rounded-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline',
                      routeConfig.id === crumb.id && 'text-foreground'
                    )}
                  >
                    {label}
                  </Link>
                )}
              </span>
            )
          })}
        </nav>
      </div>
      {actionsSlot && <div className="flex shrink-0 items-center gap-2">{actionsSlot}</div>}
    </div>
  )
}
