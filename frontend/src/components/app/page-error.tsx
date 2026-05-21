import { CircleAlert } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"

export function PageError({ title, message }: { title?: string; message: string }) {
  return (
    <Alert variant="destructive" className="panel border-destructive/30">
      <CircleAlert className="size-5" />
      <AlertTitle>{title ?? "Не удалось загрузить"}</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}
