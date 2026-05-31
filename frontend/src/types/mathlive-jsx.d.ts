import type { DetailedHTMLProps, HTMLAttributes } from 'react'

type MathFieldElementProps = DetailedHTMLProps<
  HTMLAttributes<HTMLElement> & {
    'read-only'?: boolean | string
    placeholder?: string
  },
  HTMLElement
>

declare global {
  interface HTMLElementTagNameMap {
    'math-field': HTMLElement
  }
}

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'math-field': MathFieldElementProps
    }
  }
}

declare module 'react/jsx-runtime' {
  namespace JSX {
    interface IntrinsicElements {
      'math-field': MathFieldElementProps
    }
  }
}

