'use client';

import { useMemo } from 'react';
import { Polyline } from 'react-leaflet';

const SEGMENTS = 14;

/** Rastro dividido em trechos com opacidade crescente: o passado recente fica nítido, o antigo some. */
export function FadingTrack({ points }: { points: [number, number][] }) {
  const segments = useMemo(() => {
    if (points.length < 2) return [];
    const size = Math.max(1, Math.ceil(points.length / SEGMENTS));
    const result: [number, number][][] = [];
    for (let i = 0; i < points.length - 1; i += size) {
      // Cada trecho começa no último ponto do anterior para não deixar falhas na linha
      result.push(points.slice(i, Math.min(points.length, i + size + 1)));
    }
    return result;
  }, [points]);

  return segments.map((segment, index) => (
    <Polyline
      key={index}
      positions={segment}
      pathOptions={{ color: '#3fd4e6', weight: 3, opacity: 0.1 + 0.85 * ((index + 1) / segments.length), lineCap: 'round', lineJoin: 'round' }}
    />
  ));
}
