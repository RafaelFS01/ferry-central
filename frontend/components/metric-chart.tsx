'use client';

import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TelemetryPoint } from '@/lib/central-api';
import { formatNumber, formatShortTime, formatTime } from '@/lib/format';

interface MetricChartProps {
  title: string;
  unit: string;
  data: TelemetryPoint[];
  pick: (point: TelemetryPoint) => number | null;
  color: string;
  decimals?: number;
  domain?: [number | 'auto', number | 'auto'];
  /** Linha de limite crítico (ex.: 90 °C) */
  threshold?: number;
}

/** Rótulos curtos no eixo Y para caber em 44 px: 2200 -> "2,2k". */
const formatAxis = (value: number) => (Math.abs(value) >= 1000 ? `${formatNumber(value / 1000, 1)}k` : formatNumber(value));

/** Série temporal compacta para o painel lateral. */
export function MetricChart({ title, unit, data, pick, color, decimals = 0, domain = ['auto', 'auto'], threshold }: MetricChartProps) {
  const series = data.map((point) => ({ time: point.time, value: pick(point) }));
  const last = series.at(-1)?.value ?? null;

  return (
    <figure className="rounded-lg border border-line bg-surface-2 p-3">
      <figcaption className="mb-1 flex items-baseline justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-muted">{title}</span>
        <span className="text-sm font-semibold">{formatNumber(last, decimals)} <span className="text-xs font-normal text-muted">{unit}</span></span>
      </figcaption>
      <div className="h-28">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
            <XAxis dataKey="time" type="number" scale="time" domain={['dataMin', 'dataMax']} tickFormatter={formatShortTime} tick={{ fontSize: 10, fill: 'var(--muted)' }} stroke="var(--line)" minTickGap={40} />
            <YAxis domain={domain} tick={{ fontSize: 10, fill: 'var(--muted)' }} stroke="var(--line)" width={44} tickFormatter={formatAxis} />
            {threshold !== undefined && <ReferenceLine y={threshold} stroke="var(--danger)" strokeDasharray="4 4" />}
            <Tooltip
              labelFormatter={(time) => formatTime(Number(time))}
              formatter={(value) => [`${formatNumber(Number(value), decimals)} ${unit}`, title]}
              contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }}
            />
            <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
