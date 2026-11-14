import type { Alert } from '@/lib/alerts';

const LEVEL_STYLE = {
  critical: 'border-danger bg-danger/10 text-danger',
  warning: 'border-warn bg-warn/10 text-warn',
} as const;

export function AlertsPanel({ alerts }: { alerts: Alert[] }) {
  if (alerts.length === 0) {
    return (
      <p className="flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2.5 text-sm text-muted">
        <span className="size-2 rounded-full bg-ok" aria-hidden /> Nenhum alerta ativo
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2" aria-live="assertive">
      {alerts.map((alert) => (
        <li key={alert.id} role="alert" className={`rounded-lg border-l-4 px-3 py-2.5 ${LEVEL_STYLE[alert.level]} ${alert.level === 'critical' ? 'animate-pulse' : ''}`}>
          <p className="text-sm font-semibold">{alert.title}</p>
          <p className="text-sm text-ink/80">{alert.detail}</p>
        </li>
      ))}
    </ul>
  );
}
