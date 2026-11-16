import { useEffect, useState } from "react";

export function usePresentationRead<T>(
  read: ((signal: AbortSignal) => Promise<T>) | null,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setData(null);
    setError("");
    setLoading(!!read);
    if (!read) return;
    const controller = new AbortController();
    Promise.resolve()
      .then(() => read(controller.signal))
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "A betöltés sikertelen.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [read]);
  return { data, error, loading };
}

export function usePresentationSearch(value: string) {
  const [query, setQuery] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setQuery(value), 300);
    return () => clearTimeout(timer);
  }, [value]);
  return query;
}
