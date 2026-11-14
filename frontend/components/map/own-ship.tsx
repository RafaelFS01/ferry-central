'use client';

import L from 'leaflet';
import { useMemo } from 'react';
import { CircleMarker, Marker, Polyline, Tooltip } from 'react-leaflet';
import type { TelemetryPoint } from '@/lib/central-api';
import { formatNumber, formatTime } from '@/lib/format';
import { projectPosition } from '@/lib/route';

/** Comprimento do vetor de proa: onde o ferry estará em 6 minutos mantendo rumo e velocidade. */
const VECTOR_MINUTES = 6;

const SHIP = '#ff8a1f';

function shipIcon(heading: number): L.DivIcon {
  return L.divIcon({
    className: 'own-ship',
    iconSize: [56, 56],
    iconAnchor: [28, 28],
    html: `<svg viewBox="0 0 56 56" width="56" height="56" style="transform:rotate(${heading}deg)">
      <circle cx="28" cy="28" r="25" fill="none" stroke="${SHIP}" stroke-opacity="0.35" />
      <circle cx="28" cy="28" r="17" fill="none" stroke="${SHIP}" stroke-opacity="0.18" />
      <path d="M28 7 C33 14 35 20 35 27 L35 45 Q35 48 32 48 L24 48 Q21 48 21 45 L21 27 C21 20 23 14 28 7 Z"
        fill="${SHIP}" stroke="#04070b" stroke-width="1.5" stroke-linejoin="round" />
      <rect x="25" y="26" width="6" height="12" rx="1.2" fill="#04070b" opacity="0.45" />
    </svg>`,
  });
}

/** Navio próprio no padrão ECDIS: silhueta orientada pela proa e vetor de rumo projetado. */
export function OwnShip({ point }: { point: TelemetryPoint }) {
  const heading = Math.round(point.heading ?? 0);
  const icon = useMemo(() => shipIcon(heading), [heading]);
  const position: [number, number] = [point.latitude, point.longitude];
  const speed = point.speedKnots ?? 0;
  const vectorEnd = projectPosition(position, heading, (speed * VECTOR_MINUTES) / 60);

  return (
    <>
      {speed > 0.5 && (
        <>
          <Polyline positions={[position, vectorEnd]} pathOptions={{ color: SHIP, weight: 2, dashArray: '2 6', lineCap: 'round' }} />
          <CircleMarker center={vectorEnd} radius={3} pathOptions={{ color: SHIP, weight: 1.5, fillColor: '#04070b', fillOpacity: 1 }} />
        </>
      )}
      <Marker position={position} icon={icon}>
        <Tooltip direction="right" offset={[24, 0]} className="chart-label">
          {formatTime(point.time)} · {formatNumber(point.speedKnots, 1)} nós · {String(heading).padStart(3, '0')}°
        </Tooltip>
      </Marker>
    </>
  );
}
