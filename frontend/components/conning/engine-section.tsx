import type { TelemetryPoint } from '@/lib/central-api';
import { LIMITS } from '@/lib/alerts';
import { formatNumber } from '@/lib/format';
import { RailSection } from './rail-section';

type Level = 'normal' | 'warning' | 'critical';

interface Reading {
  label: string;
  value: number | null;
  unit: string;
  decimals: number;
  /** Fração 0–1 da escala, para a barra fina */
  scale: (value: number) => number;
  level: (value: number) => Level;
}

const READINGS: ((point: TelemetryPoint | null) => Reading)[] = [
  (p) => ({ label: 'Rotação', value: p?.rpm ?? null, unit: 'rpm', decimals: 0, scale: (v) => v / 2200, level: () => 'normal' }),
  (p) => ({
    label: 'Motor',
    value: p?.engineTempC ?? null,
    unit: '°C',
    decimals: 1,
    scale: (v) => (v - 60) / 40,
    level: (v) => (v > LIMITS.engineTempCritical ? 'critical' : v >= LIMITS.engineTempWarning ? 'warning' : 'normal'),
  }),
  (p) => ({ label: 'Combustível', value: p?.fuelPercent ?? null, unit: '%', decimals: 0, scale: (v) => v / 100, level: (v) => (v < LIMITS.fuelLowPercent ? 'warning' : 'normal') }),
  (p) => ({ label: 'Bateria', value: p?.batteryV ?? null, unit: 'V', decimals: 1, scale: (v) => (v - 22) / 8, level: (v) => (v < LIMITS.batteryLowV ? 'warning' : 'normal') }),
];

const LEVEL_TEXT: Record<Level, string> = { normal: 'text-ink', warning: 'text-warn', critical: 'text-danger' };
const LEVEL_BAR: Record<Level, string> = { normal: 'bg-track', warning: 'bg-warn', critical: 'bg-danger' };

/** Leituras de máquinas com uma barra fina de escala; a cor muda só quando há alarme. */
export function EngineSection({ latest }: { latest: TelemetryPoint | null }) {
  return (
    <RailSection title="Máquinas">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5">
        {READINGS.map((build) => {
          const reading = build(latest);
          const level = reading.value === null ? 'normal' : reading.level(reading.value);
          const fill = reading.value === null ? 0 : Math.min(1, Math.max(0, reading.scale(reading.value)));
          return (
            <div key={reading.label}>
              <dt className="text-sm text-muted">{reading.label}</dt>
              <dd className={`mt-1 font-mono text-2xl font-medium leading-none ${LEVEL_TEXT[level]}`}>
                {formatNumber(reading.value, reading.decimals)}
                <span className="ml-1 text-xs font-normal text-muted">{reading.unit}</span>
              </dd>
              <div className="mt-2.5 h-[3px] rounded-full bg-line" aria-hidden>
                <div className={`bar-fill h-full rounded-full ${LEVEL_BAR[level]}`} style={{ width: `${fill * 100}%` }} />
              </div>
            </div>
          );
        })}
      </dl>
    </RailSection>
  );
}
