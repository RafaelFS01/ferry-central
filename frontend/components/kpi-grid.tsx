import type { TelemetryPoint } from '@/lib/central-api';
import { LIMITS } from '@/lib/alerts';
import { formatNumber } from '@/lib/format';

interface Kpi {
  label: string;
  value: string;
  unit: string;
  critical?: boolean;
}

function kpisOf(point: TelemetryPoint | null): Kpi[] {
  const temp = point?.engineTempC ?? null;
  return [
    { label: 'Velocidade', value: formatNumber(point?.speedKnots ?? null, 1), unit: 'nós' },
    { label: 'Rumo', value: formatNumber(point?.heading ?? null), unit: '°' },
    { label: 'Rotação', value: formatNumber(point?.rpm ?? null), unit: 'rpm' },
    { label: 'Motor', value: formatNumber(temp, 1), unit: '°C', critical: temp !== null && temp > LIMITS.engineTempCritical },
    { label: 'Bateria', value: formatNumber(point?.batteryV ?? null, 1), unit: 'V' },
    { label: 'Combustível', value: formatNumber(point?.fuelPercent ?? null, 0), unit: '%' },
  ];
}

export function KpiGrid({ latest }: { latest: TelemetryPoint | null }) {
  return (
    <dl className="grid grid-cols-3 gap-2">
      {kpisOf(latest).map((kpi) => (
        <div key={kpi.label} className={`rounded-lg border p-3 ${kpi.critical ? 'border-danger bg-danger/10' : 'border-line bg-surface-2'}`}>
          <dt className="text-xs font-medium uppercase tracking-wider text-muted">{kpi.label}</dt>
          <dd className={`mt-1 text-xl font-semibold ${kpi.critical ? 'text-danger' : 'text-ink'}`}>
            {kpi.value}
            <span className="ml-1 text-xs font-normal text-muted">{kpi.unit}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}
