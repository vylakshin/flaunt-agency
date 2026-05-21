import { toast } from "sonner"

export type NoticeType = "success" | "error" | "warning" | "info"

export function showNotice(type: NoticeType, title: string, text?: string) {
  const options = text ? { description: text } : undefined
  if (type === "success") toast.success(title, options)
  else if (type === "error") toast.error(title, options)
  else if (type === "warning") toast.warning(title, options)
  else toast.info(title, options)
}
