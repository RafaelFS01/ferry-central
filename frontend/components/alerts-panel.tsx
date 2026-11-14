import type { Alert } from '@/lib/alerts';

const LEVEL_STYLE = {
  critical: { row: 'border-danger bg-danger/10', title: 'text-danger', tag: 'Alarme' },
  warning: { row: 'border-warn bg-warn/10', title: 'text-warn', tag: 'Atenção' },
} as const;

/** Lista de alarmes no padrão da carta eletrônica: faixa colorida, nível e descrição. */
export function AlertsPanel({ alerts }: { alerts: Alert[] }) {
  if (alerts.length === 0) {
    return (
      <p className="flex items-center gap-2 font-mono text-sm text-muted">
        <span className="size-1.5 rounded-full bg-ok" aria-hidden /> Sem alarmes ativos
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2" aria-live="assertive">
      {alerts.map((alert) => {
        const style = LEVEL_STYLE[alert.level];
        return (
          <li key={alert.id} role="alert" className={`rounded-md border-l-[3px] px-3 py-2.5 ${style.row}`}>
            <p className="flex items-baseline justify-between gap-3">
              <span className={`text-sm font-medium ${style.title}`}>{alert.title}</span>
              <span className={`font-mono text-[0.625rem] uppercase tracking-[0.14em] ${style.title}`}>{style.tag}</span>
            </p>
            <p className="mt-0.5 font-mono text-xs text-ink/75">{alert.detail}</p>
          </li>
        );
      })}
    </ul>
  );
}
