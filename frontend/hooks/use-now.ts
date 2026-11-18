'use client';

import { useEffect, useState } from 'react';

/** Relógio que re-renderiza a cada `tickMs`, para rótulos como "há 5 s". */
export function useNow(tickMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), tickMs);
    return () => clearInterval(id);
  }, [tickMs]);
  return now;
}
