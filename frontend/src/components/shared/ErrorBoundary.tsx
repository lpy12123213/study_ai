import { Component, type ReactNode } from 'react'
import { AlertCircle, Home, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error?: Error
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: undefined })
  }

  handleGoHome = () => {
    // Use window.location instead of <Link> to avoid Router context dependency
    window.location.href = '/dashboard'
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      return (
        <div className="aurora-error-boundary flex h-full flex-col items-center justify-center p-8 text-center">
          <div className="aurora-error-boundary-card">
            <AlertCircle className="h-12 w-12 text-destructive mb-4" />
            <h2 className="text-lg font-semibold mb-2">出错了</h2>
            <p className="text-muted-foreground mb-4 max-w-md">
              {this.state.error?.message || '发生了一个未知错误'}
            </p>
            <div className="flex items-center gap-2">
              <Button className="aurora-shared-secondary-action" onClick={this.handleGoHome} variant="outline">
                <Home className="h-4 w-4 mr-2" />
                返回首页
              </Button>
              <Button className="aurora-shared-primary-action" onClick={this.handleRetry} variant="outline">
                <RefreshCw className="h-4 w-4 mr-2" />
                重试
              </Button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
