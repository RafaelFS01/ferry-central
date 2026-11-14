import type { TelemetryPoint } from '@/lib/central-api';
import { formatCoordinate } from '@/lib/format';

/** Relógio em UTC, a referência de tempo das comunicações marítimas. */
export function UtcClock({ now }: { now: number }) {
  const utc = new Date(now).toISOString().slice(11, 19);
  return (
    <div className="flex items-baseline gap-2 rounded-lg border border-line bg-surface/95 px-3 py-2.5 font-mono">
      <span className="text-base font-medium" suppressHydrationWarning>{utc}</span>
      <span className="text-[0.6875rem] text-muted">UTC</span>
    </div>
  );
}

export function FollowToggle({ follow, onToggle }: { follow: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={follow}
      className={`press rounded-lg border px-4 py-2.5 font-mono text-xs font-medium uppercase tracking-[0.12em] ${
        follow ? 'border-ship bg-ship text-bg' : 'border-line bg-surface/95 text-ink hover:border-muted'
      }`}
    >
      {follow ? 'Seguindo o ferry' : 'Seguir o ferry'}
    </button>
  );
}

/** Caixa de posição no canto da carta, em graus e minutos. */
export function PositionReadout({ latest }: { latest: TelemetryPoint | null }) {
  if (!latest) return null;
  return (
    <dl className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5 rounded-lg border border-line bg-surface/95 px-4 py-2.5 font-mono text-xs">
      <dt className="text-muted">LAT</dt>
      <dd>{formatCoordinate(latest.latitude, 'lat')}</dd>
      <dt className="text-muted">LON</dt>
      <dd>{formatCoordinate(latest.longitude, 'lon')}</dd>
    </dl>
  );
}
