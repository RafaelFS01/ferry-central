'use client';

import { useState } from 'react';
import { useNow } from '@/hooks/use-now';
import { useTelemetryFeed } from '@/hooks/use-telemetry-feed';
import { evaluateAlerts, LIMITS } from '@/lib/alerts';
import { AlertsPanel } from './alerts-panel';
import { FollowToggle, PositionReadout, UtcClock } from './chart-overlays';
import { EngineSection } from './conning/engine-section';
import { NavigationSection } from './conning/navigation-section';
import { PassageSection } from './conning/passage-section';
import { RailSection } from './conning/rail-section';
import { MapView } from './map/map-view';
import { MetricChart } from './metric-chart';
import { VesselPlate } from './vessel-plate';

export function Dashboard() {
  const { track, latest, apiReachable, loading } = useTelemetryFeed();
  const now = useNow();
  const [follow, setFollow] = useState(true);
  const alerts = evaluateAlerts(latest, now);

  return (
    <div className="flex min-h-dvh flex-col lg:h-dvh lg:flex-row">
      <div className="relative h-[70dvh] shrink-0 lg:h-auto lg:flex-1">
        <MapView track={track} latest={latest} follow={follow} />

        {/* Sobreposições da carta; a camada não captura cliques fora dos próprios elementos */}
        <div className="pointer-events-none absolute inset-0 z-[1000] flex flex-col justify-between p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="pointer-events-auto max-w-md">
              <VesselPlate latest={latest} apiReachable={apiReachable} loading={loading} now={now} />
            </div>
            <div className="pointer-events-auto flex items-center gap-2">
              <UtcClock now={now} />
              <FollowToggle follow={follow} onToggle={() => setFollow((value) => !value)} />
            </div>
          </div>
          <div className="pointer-events-auto self-start">
            <PositionReadout latest={latest} />
          </div>
        </div>
      </div>

      <aside className="flex flex-col border-line bg-surface lg:w-[420px] lg:overflow-y-auto lg:border-l">
        <RailSection title="Alarmes" aside={alerts.length > 0 && <span className="font-mono text-xs text-danger">{alerts.length} ativo(s)</span>}>
          <AlertsPanel alerts={alerts} />
        </RailSection>
        <PassageSection latest={latest} now={now} />
        <NavigationSection latest={latest} />
        <EngineSection latest={latest} />
        <RailSection title="Histórico" aside={<span className="font-mono text-xs text-muted">{track.length} leituras</span>}>
          <div className="flex flex-col gap-5">
            <MetricChart title="Velocidade" unit="nós" data={track} pick={(p) => p.speedKnots} color="#3fd4e6" decimals={1} domain={[0, 16]} />
            <MetricChart title="Rotação" unit="rpm" data={track} pick={(p) => p.rpm} color="#7fe0b4" domain={[0, 2200]} />
            <MetricChart
              title="Temperatura do motor"
              unit="°C"
              data={track}
              pick={(p) => p.engineTempC}
              color="#ff8a1f"
              decimals={1}
              domain={[70, 100]}
              threshold={LIMITS.engineTempCritical}
            />
          </div>
        </RailSection>
      </aside>
    </div>
  );
}
