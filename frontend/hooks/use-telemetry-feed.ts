'use client';

import { useEffect, useState } from 'react';
import { fetchHistory, fetchLatest, type TelemetryPoint } from '@/lib/central-api';

export interface TelemetryFeed {
  /** Rastro em ordem cronológica, incluindo a leitura mais recente */
  track: TelemetryPoint[];
  latest: TelemetryPoint | null;
  apiReachable: boolean;
  loading: boolean;
}

interface FeedOptions {
  latestEveryMs?: number;
  historyEveryMs?: number;
  /** 720 pontos = 1 h de travessia com coleta a cada 5 s */
  historyLimit?: number;
}

function mergeTrack(track: TelemetryPoint[], incoming: TelemetryPoint[], limit: number): TelemetryPoint[] {
  const byId = new Map(track.map((point) => [point.id, point]));
  for (const point of incoming) byId.set(point.id, point);
  return [...byId.values()].sort((a, b) => a.time - b.time).slice(-limit);
}

/**
 * Pooling suave da API Central: a última leitura em intervalo curto e o
 * histórico em intervalo longo, sem recarregar a página.
 */
export function useTelemetryFeed({ latestEveryMs = 3000, historyEveryMs = 15000, historyLimit = 720 }: FeedOptions = {}): TelemetryFeed {
  const [feed, setFeed] = useState<TelemetryFeed>({ track: [], latest: null, apiReachable: true, loading: true });

  useEffect(() => {
    const controller = new AbortController();
    const timers: ReturnType<typeof setTimeout>[] = [];

    const schedule = (task: () => Promise<void>, everyMs: number) => {
      const run = async () => {
        await task();
        if (!controller.signal.aborted) timers.push(setTimeout(run, everyMs));
      };
      void run();
    };

    const apply = (result: Awaited<ReturnType<typeof fetchLatest>>) => {
      if (controller.signal.aborted) return;
      setFeed((previous) => {
        if (!result.ok) return { ...previous, apiReachable: false, loading: false };
        const track = mergeTrack(previous.track, result.data, historyLimit);
        // Mantém uma única embarcação: a da leitura mais recente
        const latest = track.at(-1) ?? null;
        const boatTrack = latest ? track.filter((point) => point.boatId === latest.boatId) : track;
        return { track: boatTrack, latest, apiReachable: true, loading: false };
      });
    };

    schedule(async () => apply(await fetchHistory(historyLimit, controller.signal)), historyEveryMs);
    schedule(async () => apply(await fetchLatest(controller.signal)), latestEveryMs);

    return () => {
      controller.abort();
      timers.forEach(clearTimeout);
    };
  }, [latestEveryMs, historyEveryMs, historyLimit]);

  return feed;
}
