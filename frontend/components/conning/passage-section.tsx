import type { TelemetryPoint } from '@/lib/central-api';
import { formatNumber } from '@/lib/format';
import { BOM_DESPACHO, passageOf, ROUTE_LENGTH_NM, SAO_JOAQUIM } from '@/lib/passage';
import { RailSection } from './rail-section';

/** Destino, distância restante e ETA, com a barra na mesma orientação da carta (Itaparica a oeste). */
export function PassageSection({ latest, now }: { latest: TelemetryPoint | null; now: number }) {
  if (!latest || latest.heading === null) {
    return (
      <RailSection title="Travessia">
        <p className="text-sm text-muted">Aguardando posição do ferry.</p>
      </RailSection>
    );
  }

  const passage = passageOf({ lat: latest.latitude, lon: latest.longitude }, latest.heading, latest.speedKnots ?? 0);
  const fromWest = (1 - passage.progress) * 100;
  const toItaparica = passage.destination === BOM_DESPACHO;
  const eta = passage.etaMinutes === null ? null : new Date(now + passage.etaMinutes * 60_000);

  return (
    <RailSection title="Travessia" aside={<span className="font-mono text-xs text-muted">{formatNumber(ROUTE_LENGTH_NM, 1)} NM</span>}>
      <p className="text-sm text-muted">Destino</p>
      <p className="text-2xl font-medium tracking-[-0.02em]">{passage.destination.name}</p>

      <div className="relative mt-5 h-1 rounded-full bg-line">
        <span
          className="bar-fill absolute inset-y-0 rounded-full bg-ship"
          style={toItaparica ? { left: `${fromWest}%`, width: `${100 - fromWest}%` } : { left: 0, width: `${fromWest}%` }}
        />
        <span className="bar-fill absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg bg-ship" style={{ left: `${fromWest}%` }} />
      </div>
      <div className="mt-2 flex justify-between font-mono text-[0.6875rem] text-muted">
        <span>{BOM_DESPACHO.name}</span>
        <span>{SAO_JOAQUIM.name}</span>
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-3 font-mono">
        <div>
          <dt className="text-[0.6875rem] text-muted">Restam</dt>
          <dd className="text-lg">{formatNumber(passage.remainingNm, 2)} <span className="text-xs text-muted">NM</span></dd>
        </div>
        <div>
          <dt className="text-[0.6875rem] text-muted">ETA</dt>
          <dd className="text-lg">{eta ? eta.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '—'}</dd>
        </div>
        <div>
          <dt className="text-[0.6875rem] text-muted">Desvio</dt>
          <dd className="text-lg">{formatNumber(passage.crossTrackNm * 1852, 0)} <span className="text-xs text-muted">m</span></dd>
        </div>
      </dl>
    </RailSection>
  );
}
