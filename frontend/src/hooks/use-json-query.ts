import { useCallback, useEffect, useState } from "react"

import { fetchJson } from "@/lib/api"

type QueryState<T> = {
  data: T | null
  isLoading: boolean
  error: string | null
}

export function useJsonQuery<T>(url: string) {
  const [state, setState] = useState<QueryState<T>>({
    data: null,
    isLoading: true,
    error: null,
  })

  const refetch = useCallback(async () => {
    setState((current) => ({
      ...current,
      // Keep the UI stable during background refresh when we already have data.
      isLoading: !current.data,
      error: null,
    }))

    try {
      const data = await fetchJson<T>(url)
      setState({ data, isLoading: false, error: null })
    } catch (error) {
      setState((current) => ({
        data: current.data,
        isLoading: false,
        error: (error as Error).message,
      }))
    }
  }, [url])

  useEffect(() => {
    void refetch()
  }, [refetch])

  return { ...state, refetch, setData: (data: T) => setState({ data, isLoading: false, error: null }) }
}
