'use client';

import { useState } from 'react';
import { useNow } from '@/hooks/use-now';
import { useTelemetryFeed } from '@/hooks/use-telemetry-feed';
import { evaluateAlerts, LIMITS } from '@/lib/alerts';
import { AlertsPanel } from './alerts-panel';
import { DashboardHeader } from './dashboard-header';
import { KpiGrid } from './kpi-grid';
import { MapView } from './map/map-view';
import { MetricChart } from './metric-chart';

function SidebarSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">{title}</h2>
      {children}
    </section>
  );
}

export function Dashboard() {
  const { track, latest, apiReachable, loading } = useTelemetryFeed();
  const now = useNow();
  const [follow, setFollow] = useState(true);
  const alerts = evaluateAlerts(latest, now);

  return (
    <div className="flex h-dvh flex-col">
      <DashboardHeader latest={latest} apiReachable={apiReachable} loading={loading} now={now} />

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="relative h-[55vh] lg:h-auto lg:flex-1">
          <MapView track={track} latest={latest} follow={follow} />
          <button
            type="button"
            onClick={() => setFollow((value) => !value)}
            aria-pressed={follow}
            className={`absolute right-3 top-3 z-[1000] rounded-lg border px-3 py-2 text-sm font-medium shadow-sm ${follow ? 'border-accent bg-accent text-white' : 'border-line bg-surface text-ink'}`}
          >
            {follow ? 'Seguindo embarcação' : 'Seguir embarcação'}
          </button>
        </div>

        <aside className="flex flex-col gap-5 overflow-y-auto border-line bg-surface p-4 lg:w-[400px] lg:border-l">
          <SidebarSection title={`Alertas${alerts.length ? ` (${alerts.length})` : ''}`}>
            <AlertsPanel alerts={alerts} />
          </SidebarSection>

          <SidebarSection title="Telemetria atual">
            <KpiGrid latest={latest} />
          </SidebarSection>

          <SidebarSection title={`Histórico · ${track.length} leituras`}>
            <MetricChart title="Velocidade" unit="nós" data={track} pick={(p) => p.speedKnots} color="#0b4f8a" decimals={1} domain={[0, 16]} />
            <MetricChart title="Rotação" unit="rpm" data={track} pick={(p) => p.rpm} color="#7c3aed" domain={[0, 2200]} />
            <MetricChart
              title="Temperatura do motor"
              unit="°C"
              data={track}
              pick={(p) => p.engineTempC}
              color="#ea580c"
              decimals={1}
              domain={[70, 100]}
              threshold={LIMITS.engineTempCritical}
            />
          </SidebarSection>
        </aside>
      </div>
    </div>
  );
}
