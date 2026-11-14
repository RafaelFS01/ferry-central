// Geografia da travessia Salvador–Itaparica na Baía de Todos-os-Santos.
import { BOM_DESPACHO, SAO_JOAQUIM, type PassageTerminal } from './passage';

export interface Terminal {
  name: string;
  city: string;
  position: [number, number];
}

const toTerminal = (terminal: PassageTerminal): Terminal => ({
  name: `Terminal ${terminal.name}`,
  city: terminal.city,
  position: [terminal.lat, terminal.lon],
});

export const TERMINALS = [toTerminal(SAO_JOAQUIM), toTerminal(BOM_DESPACHO)] as const;

/** Rota nominal (ortodrômica) usada pelo simulador. */
export const NOMINAL_ROUTE: [number, number][] = TERMINALS.map((terminal) => terminal.position);

export const MAP_CENTER: [number, number] = [-12.9628, -38.5376];
export const MAP_ZOOM = 13;

/** Posição estimada após navegar `distanceNm` no rumo dado (vetor de proa da carta). */
export function projectPosition([lat, lon]: [number, number], headingDeg: number, distanceNm: number): [number, number] {
  const rad = (headingDeg * Math.PI) / 180;
  const dLat = (distanceNm * Math.cos(rad)) / 60;
  const dLon = (distanceNm * Math.sin(rad)) / (60 * Math.cos((lat * Math.PI) / 180));
  return [lat + dLat, lon + dLon];
}
