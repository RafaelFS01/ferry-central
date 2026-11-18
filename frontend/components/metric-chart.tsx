'use client';

import { useId } from 'react';
import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
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

/** Série temporal em área com degradê, sem moldura, para o rail de conning. */
export function MetricChart({ title, unit, data, pick, color, decimals = 0, domain = ['auto', 'auto'], threshold }: MetricChartProps) {
  const gradientId = `fill-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const series = data.map((point) => ({ time: point.time, value: pick(point) }));
  const last = series.at(-1)?.value ?? null;

  return (
    <figure>
      <figcaption className="mb-2 flex items-baseline justify-between">
        <span className="text-sm text-muted">{title}</span>
        <span className="font-mono text-sm">
          {formatNumber(last, decimals)} <span className="text-xs text-muted">{unit}</span>
        </span>
      </figcaption>
      <div className="h-24">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor={color} stopOpacity={0.35} />
                <stop offset="1" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="time"
              type="number"
              scale="time"
              domain={['dataMin', 'dataMax']}
              tickFormatter={formatShortTime}
              tick={{ fontSize: 10, fill: 'var(--muted)', fontFamily: 'var(--font-jetbrains)' }}
              stroke="var(--line)"
              tickLine={false}
              minTickGap={48}
            />
            <YAxis domain={domain} hide />
            {threshold !== undefined && <ReferenceLine y={threshold} stroke="var(--danger)" strokeDasharray="3 4" strokeOpacity={0.8} />}
            <Tooltip
              labelFormatter={(time) => formatTime(Number(time))}
              formatter={(value) => [`${formatNumber(Number(value), decimals)} ${unit}`, title]}
              contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 6, fontSize: 12, fontFamily: 'var(--font-jetbrains)' }}
              labelStyle={{ color: 'var(--muted)' }}
              itemStyle={{ color: 'var(--ink)' }}
              cursor={{ stroke: 'var(--muted)', strokeDasharray: '2 3' }}
            />
            <Area type="monotone" dataKey="value" stroke={color} strokeWidth={1.75} fill={`url(#${gradientId})`} isAnimationActive={false} connectNulls />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
