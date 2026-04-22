/** Debounce a value by a fixed delay. */
import { useEffect, useState } from "react";

export function useDebounced<T>(value: T, delay = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return v;
}
