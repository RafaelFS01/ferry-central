'use client';

import 'leaflet/dist/leaflet.css';
import { useEffect, useMemo } from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet';
import type { TelemetryPoint } from '@/lib/central-api';
import { MAP_CENTER, MAP_ZOOM, NOMINAL_ROUTE, TERMINALS } from '@/lib/route';
import { FadingTrack } from './fading-track';
import { OwnShip } from './own-ship';

interface NauticalMapProps {
  track: TelemetryPoint[];
  latest: TelemetryPoint | null;
  follow: boolean;
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
  const position: [number, number] | null = latest ? [latest.latitude, latest.longitude] : null;

  return (
    <MapContainer center={MAP_CENTER} zoom={MAP_ZOOM} className="size-full" zoomControl={false} attributionControl>
      <TileLayer
        className="chart-base"
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        maxZoom={18}
      />
      {/* Marcas náuticas (boias, faróis, canais) do OpenSeaMap sobre a base */}
      <TileLayer
        className="chart-seamarks"
        url="https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openseamap.org">OpenSeaMap</a>'
        maxZoom={18}
      />

      <Polyline positions={NOMINAL_ROUTE} pathOptions={{ color: '#7f8f9e', weight: 1.5, opacity: 0.7, dashArray: '8 8' }} />
      <FadingTrack points={breadcrumbs} />

      {TERMINALS.map((terminal) => (
        <CircleMarker key={terminal.name} center={terminal.position} radius={6} pathOptions={{ color: '#e3eaf0', weight: 2, fillColor: '#04070b', fillOpacity: 1 }}>
          <Tooltip direction="top" offset={[0, -10]} permanent className="chart-label">
            {terminal.name} · {terminal.city}
          </Tooltip>
        </CircleMarker>
      ))}

      {latest && <OwnShip point={latest} />}
      <FollowBoat position={position} follow={follow} />
    </MapContainer>
  );
}
