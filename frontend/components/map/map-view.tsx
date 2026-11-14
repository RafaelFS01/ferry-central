'use client';

import dynamic from 'next/dynamic';

// Leaflet depende de `window`: o mapa só é carregado no navegador.
export const MapView = dynamic(() => import('./nautical-map').then((module) => module.NauticalMap), {
  ssr: false,
  loading: () => (
    <div className="grid size-full place-items-center bg-surface-2 text-muted">Carregando carta náutica…</div>
  ),
});
