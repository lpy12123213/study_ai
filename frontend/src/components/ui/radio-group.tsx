import * as React from 'react'
import { Circle } from 'lucide-react'
import { cn } from '@/lib/utils'

type RadioGroupContextValue = {
  value: string
  onValueChange?: (value: string) => void
  name: string
}

const RadioGroupContext = React.createContext<RadioGroupContextValue | null>(null)

interface RadioGroupProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: string
  defaultValue?: string
  onValueChange?: (value: string) => void
  name?: string
}

const RadioGroup = React.forwardRef<HTMLDivElement, RadioGroupProps>(
  ({ className, value, defaultValue = '', onValueChange, name, children, ...props }, ref) => {
    const [internalValue, setInternalValue] = React.useState(defaultValue)
    const current = value ?? internalValue
    const groupName = React.useId()
    const ctx = React.useMemo(
      () => ({
        value: current,
        onValueChange: (next: string) => {
          setInternalValue(next)
          onValueChange?.(next)
        },
        name: name || groupName,
      }),
      [current, groupName, name, onValueChange]
    )
    return (
      <RadioGroupContext.Provider value={ctx}>
        <div ref={ref} role="radiogroup" className={cn('aurora-ui-radio-group grid gap-2', className)} {...props}>
          {children}
        </div>
      </RadioGroupContext.Provider>
    )
  }
)
RadioGroup.displayName = 'RadioGroup'

interface RadioGroupItemProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type' | 'onChange'> {
  value: string
}

const RadioGroupItem = React.forwardRef<HTMLInputElement, RadioGroupItemProps>(({ className, value, ...props }, ref) => {
  const ctx = React.useContext(RadioGroupContext)
  const checked = ctx?.value === value
  return (
    <span
      className={cn(
        'aurora-ui-radio-item inline-flex h-4 w-4 items-center justify-center rounded-full border border-primary text-primary',
        checked && 'aurora-ui-radio-item-checked bg-primary text-primary-foreground',
        className
      )}
    >
      <input
        ref={ref}
        type="radio"
        className="sr-only"
        name={ctx?.name}
        value={value}
        checked={checked}
        onChange={() => ctx?.onValueChange?.(value)}
        {...props}
      />
      {checked && <Circle className="h-2 w-2 fill-current" />}
    </span>
  )
})
RadioGroupItem.displayName = 'RadioGroupItem'

export { RadioGroup, RadioGroupItem }
