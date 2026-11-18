import type { TelemetryPoint } from '@/lib/central-api';
import { boatName, formatAge } from '@/lib/format';

interface VesselPlateProps {
  latest: TelemetryPoint | null;
  apiReachable: boolean;
  loading: boolean;
  now: number;
}

function feedStatus({ latest, apiReachable, loading }: Omit<VesselPlateProps, 'now'>) {
  if (loading) return { label: 'Conectando à API Central', dot: 'bg-muted' };
  if (!apiReachable) return { label: 'API Central indisponível', dot: 'bg-danger' };
  if (!latest) return { label: 'Aguardando primeira telemetria', dot: 'bg-warn' };
  return { label: 'Recebendo telemetria', dot: 'bg-ok' };
}

/** Placa da embarcação sobre a carta: nome, travessia e estado do enlace com a API. */
export function VesselPlate({ latest, apiReachable, loading, now }: VesselPlateProps) {
  const status = feedStatus({ latest, apiReachable, loading });

  return (
    <header className="rounded-xl border border-line bg-surface/95 px-5 py-4 shadow-[0_20px_40px_-24px_rgb(0_0_0/0.9)]">
      <p className="engraved">Central de operações · Baía de Todos-os-Santos</p>
      <h1 className="mt-1 text-3xl font-medium tracking-[-0.03em] sm:text-4xl">
        {latest ? boatName(latest.boatId) : 'Carta náutica'}
      </h1>
      <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs">
        <span className="text-muted">Salvador ⇄ Itaparica</span>
        <span className="flex items-center gap-1.5">
          <span className={`size-1.5 rounded-full ${status.dot}`} aria-hidden />
          {status.label}
        </span>
        {latest && <span className="text-muted">{formatAge(latest.time, now)}</span>}
      </p>
    </header>
  );
}
