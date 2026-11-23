import type { TelemetryPoint } from '@/lib/central-api';
import { formatNumber } from '@/lib/format';
import { RailSection } from './rail-section';

/** Capacidade de passageiros do ferry (mesmo limite do contrato e do simulador). */
const CAPACITY = 1000;

/** Lotação informada pelo barco na leitura mais recente, com a ocupação em barra. */
export function OccupancySection({ latest }: { latest: TelemetryPoint | null }) {
  const passengers = latest?.passengers ?? null;
  const occupancy = passengers === null ? 0 : Math.min(1, passengers / CAPACITY);

  return (
    <RailSection title="Lotação" aside={<span className="font-mono text-xs text-muted">capacidade {formatNumber(CAPACITY, 0)}</span>}>
      <p className="font-mono text-5xl font-medium leading-none tracking-tight">
        {formatNumber(passengers, 0)}
        <span className="ml-1.5 text-sm font-normal text-muted">a bordo</span>
      </p>
      <div className="relative mt-4 h-1 rounded-full bg-line" role="meter" aria-label="Ocupação" aria-valuemin={0} aria-valuemax={CAPACITY} aria-valuenow={passengers ?? undefined}>
        <span className={`bar-fill absolute inset-y-0 left-0 rounded-full ${occupancy >= 0.95 ? 'bg-warn' : 'bg-ship'}`} style={{ width: `${occupancy * 100}%` }} />
      </div>
      <p className="mt-2 font-mono text-[0.6875rem] text-muted">
        {passengers === null ? 'sem dado de lotação' : `${formatNumber(occupancy * 100, 0)}% ocupado`}
      </p>
    </RailSection>
  );
}
