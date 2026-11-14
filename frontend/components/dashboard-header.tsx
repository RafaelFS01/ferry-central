import type { TelemetryPoint } from '@/lib/central-api';
import { boatName, formatAge, formatTime } from '@/lib/format';

interface DashboardHeaderProps {
  latest: TelemetryPoint | null;
  apiReachable: boolean;
  loading: boolean;
  now: number;
}

function feedStatus({ latest, apiReachable, loading }: Omit<DashboardHeaderProps, 'now'>) {
  if (loading) return { label: 'Conectando à API Central…', dot: 'bg-muted' };
  if (!apiReachable) return { label: 'API Central indisponível', dot: 'bg-danger' };
  if (!latest) return { label: 'Aguardando primeira telemetria', dot: 'bg-warn' };
  return { label: 'Recebendo telemetria', dot: 'bg-ok' };
}

export function DashboardHeader({ latest, apiReachable, loading, now }: DashboardHeaderProps) {
  const status = feedStatus({ latest, apiReachable, loading });

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted">Central de Operações · Baía de Todos-os-Santos</p>
        <h1 className="text-xl font-semibold">
          {latest ? `Ferry ${boatName(latest.boatId)}` : 'Dashboard Cartográfico Náutico'}
          <span className="ml-2 text-base font-normal text-muted">Salvador ⇄ Itaparica</span>
        </h1>
      </div>
      <div className="flex items-center gap-4 text-sm">
        <span className="flex items-center gap-2">
          <span className={`size-2.5 rounded-full ${status.dot}`} aria-hidden />
          {status.label}
        </span>
        {latest && (
          <span className="text-muted">
            Última leitura {formatTime(latest.time)} · {formatAge(latest.time, now)}
          </span>
        )}
      </div>
    </header>
  );
}
