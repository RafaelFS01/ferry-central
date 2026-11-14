// Regras de alerta operacional avaliadas sobre a leitura mais recente.
// Sem imports de runtime: roda direto no `node --test` com type stripping.

export type AlertLevel = 'critical' | 'warning';

export interface Alert {
  id: string;
  level: AlertLevel;
  title: string;
  detail: string;
}

export interface AlertInput {
  time: number;
  engineTempC: number | null;
  batteryV: number | null;
  fuelPercent: number | null;
}

export const LIMITS = {
  engineTempCritical: 90,
  engineTempWarning: 88,
  batteryLowV: 23.5,
  fuelLowPercent: 15,
  /** Sem telemetria nova por mais tempo que isso indica partição de rede */
  staleAfterMs: 30_000,
} as const;

const fmt = (value: number, decimals = 1) => value.toLocaleString('pt-BR', { maximumFractionDigits: decimals });

export function evaluateAlerts(latest: AlertInput | null, now: number): Alert[] {
  if (!latest) return [];
  const alerts: Alert[] = [];
  const { engineTempC, batteryV, fuelPercent } = latest;

  if (engineTempC !== null && engineTempC > LIMITS.engineTempCritical) {
    alerts.push({ id: 'engine-temp', level: 'critical', title: 'Superaquecimento do motor', detail: `${fmt(engineTempC)} °C — acima de ${LIMITS.engineTempCritical} °C` });
  } else if (engineTempC !== null && engineTempC >= LIMITS.engineTempWarning) {
    alerts.push({ id: 'engine-temp', level: 'warning', title: 'Temperatura do motor elevada', detail: `${fmt(engineTempC)} °C — próximo do limite de ${LIMITS.engineTempCritical} °C` });
  }

  if (batteryV !== null && batteryV < LIMITS.batteryLowV) {
    alerts.push({ id: 'battery', level: 'warning', title: 'Tensão de bateria baixa', detail: `${fmt(batteryV)} V — abaixo de ${fmt(LIMITS.batteryLowV)} V` });
  }

  if (fuelPercent !== null && fuelPercent < LIMITS.fuelLowPercent) {
    alerts.push({ id: 'fuel', level: 'warning', title: 'Combustível baixo', detail: `${fmt(fuelPercent, 0)}% no tanque` });
  }

  const silenceMs = now - latest.time;
  if (silenceMs > LIMITS.staleAfterMs) {
    alerts.push({ id: 'stale', level: 'critical', title: 'Sem telemetria recente', detail: `Última leitura há ${Math.round(silenceMs / 1000)} s — possível partição de rede` });
  }

  return alerts.sort((a, b) => (a.level === b.level ? 0 : a.level === 'critical' ? -1 : 1));
}
