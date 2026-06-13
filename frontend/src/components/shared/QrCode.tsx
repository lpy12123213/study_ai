import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import QRCode from 'qrcode'

export function QrCode(props: { text: string; size?: number; className?: string }) {
  const { text, size = 180, className } = props
  const [dataUrl, setDataUrl] = useState<string>('')

  useEffect(() => {
    let active = true
    const value = String(text || '').trim()
    if (!value) {
      setDataUrl('')
      return
    }

    QRCode.toDataURL(value, { width: size, margin: 1 })
      .then((url: string) => {
        if (!active) return
        setDataUrl(url)
      })
      .catch(() => {
        if (!active) return
        setDataUrl('')
      })

    return () => {
      active = false
    }
  }, [text, size])

  if (!dataUrl) return null
  return <img src={dataUrl} alt="QR Code" className={cn('aurora-qr-code', className)} width={size} height={size} />
}
