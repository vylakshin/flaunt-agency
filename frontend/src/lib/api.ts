export async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
    },
  })

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`)
  }

  return response.json() as Promise<T>
}

export async function requestJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
  })

  const contentType = response.headers.get("content-type") || ""
  const payload = contentType.includes("application/json") ? await response.json() : null

  if (!response.ok) {
    throw new Error(payload?.error ?? `Request failed: ${response.status}`)
  }

  if (payload?.ok === false) {
    throw new Error(payload.error ?? "Request failed")
  }

  return payload as T
}

export async function requestForm<T>(url: string, formData: FormData): Promise<T> {
  return requestJson<T>(url, {
    method: "POST",
    body: formData,
  })
}
