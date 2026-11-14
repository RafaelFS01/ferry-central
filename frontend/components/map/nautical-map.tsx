'use client';

import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { useEffect, useMemo } from 'react';
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet';
import type { TelemetryPoint } from '@/lib/central-api';
import { formatNumber, formatTime } from '@/lib/format';
import { MAP_CENTER, MAP_ZOOM, NOMINAL_ROUTE, TERMINALS } from '@/lib/route';

interface NauticalMapProps {
  track: TelemetryPoint[];
  latest: TelemetryPoint | null;
  follow: boolean;
}

function boatIcon(heading: number): L.DivIcon {
  return L.divIcon({
    className: 'boat-marker',
    iconSize: [40, 40],
    iconAnchor: [20, 20],
    html: `<svg viewBox="0 0 40 40" width="40" height="40" style="transform:rotate(${heading}deg)">
      <circle cx="20" cy="20" r="17" fill="rgba(11,79,138,0.18)" />
      <path d="M20 5 L28 30 L20 25 L12 30 Z" fill="#0b4f8a" stroke="#fff" stroke-width="2" stroke-linejoin="round" />
    </svg>`,
  });
}

/** Mantém a embarcação centralizada enquanto o modo "seguir" estiver ativo. */
function FollowBoat({ position, follow }: { position: [number, number] | null; follow: boolean }) {
  const map = useMap();
  const [lat, lng] = position ?? [];
  useEffect(() => {
    if (follow && lat !== undefined && lng !== undefined) map.panTo([lat, lng], { animate: true, duration: 0.8 });
  }, [map, follow, lat, lng]);
  return null;
}

export function NauticalMap({ track, latest, follow }: NauticalMapProps) {
  const breadcrumbs = useMemo(() => track.map((point) => [point.latitude, point.longitude] as [number, number]), [track]);
  const heading = Math.round(latest?.heading ?? 0);
  const icon = useMemo(() => boatIcon(heading), [heading]);
  const position: [number, number] | null = latest ? [latest.latitude, latest.longitude] : null;

  return (
    <MapContainer center={MAP_CENTER} zoom={MAP_ZOOM} className="size-full" zoomControl={false} attributionControl>
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        maxZoom={18}
      />
      {/* Marcas náuticas (boias, faróis, canais) do OpenSeaMap sobre a base */}
      <TileLayer
        url="https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openseamap.org">OpenSeaMap</a>'
        maxZoom={18}
      />

      <Polyline positions={NOMINAL_ROUTE} pathOptions={{ color: '#475569', weight: 2, dashArray: '6 8' }} />
      {breadcrumbs.length > 1 && (
        <Polyline positions={breadcrumbs} pathOptions={{ color: '#ea580c', weight: 4, opacity: 0.9, lineJoin: 'round' }} />
      )}

      {TERMINALS.map((terminal) => (
        <CircleMarker
          key={terminal.name}
          center={terminal.position}
          radius={8}
          pathOptions={{ color: '#fff', weight: 2, fillColor: '#0f172a', fillOpacity: 1 }}
        >
          <Tooltip direction="top" offset={[0, -8]} permanent>
            <strong>{terminal.name}</strong> · {terminal.city}
          </Tooltip>
        </CircleMarker>
      ))}

      {latest && position && (
        <Marker position={position} icon={icon}>
          <Tooltip direction="right" offset={[16, 0]}>
            {formatTime(latest.time)} · {formatNumber(latest.speedKnots, 1)} nós · rumo {formatNumber(latest.heading)}°
          </Tooltip>
        </Marker>
      )}

      <FollowBoat position={position} follow={follow} />
    </MapContainer>
  );
}
