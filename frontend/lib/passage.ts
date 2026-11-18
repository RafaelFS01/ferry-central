// Progresso na travessia Salvador–Itaparica a partir da posição GPS.
// Sem imports: roda direto no `node --test` com type stripping.

export interface GeoPoint {
  lat: number;
  lon: number;
}

export interface PassageTerminal extends GeoPoint {
  name: string;
  city: string;
}

// Mesmas coordenadas do simulador (src/simulator/route.ts)
export const SAO_JOAQUIM: PassageTerminal = { name: 'São Joaquim', city: 'Salvador', lat: -12.9482, lon: -38.5028 };
export const BOM_DESPACHO: PassageTerminal = { name: 'Bom Despacho', city: 'Itaparica', lat: -12.9774, lon: -38.5724 };

const toRad = (deg: number) => (deg * Math.PI) / 180;

/** Projeção plana local em milhas náuticas (1' de latitude = 1 NM); precisa o bastante para uma travessia de 4 NM. */
function toNm(point: GeoPoint, origin: GeoPoint) {
  return { x: (point.lon - origin.lon) * 60 * Math.cos(toRad(origin.lat)), y: (point.lat - origin.lat) * 60 };
}

const ROUTE = toNm(BOM_DESPACHO, SAO_JOAQUIM);
export const ROUTE_LENGTH_NM = Math.hypot(ROUTE.x, ROUTE.y);
/** Rumo verdadeiro de São Joaquim para Bom Despacho */
export const ROUTE_BEARING = ((Math.atan2(ROUTE.x, ROUTE.y) * 180) / Math.PI + 360) % 360;

export interface Passage {
  /** 0 em São Joaquim, 1 em Bom Despacho */
  progress: number;
  destination: PassageTerminal;
  remainingNm: number;
  /** null com a embarcação parada (menos de 1 nó) */
  etaMinutes: number | null;
  /** Afastamento lateral em relação à rota nominal */
  crossTrackNm: number;
}

export function passageOf(position: GeoPoint, headingDeg: number, speedKnots: number): Passage {
  const p = toNm(position, SAO_JOAQUIM);
  const along = (p.x * ROUTE.x + p.y * ROUTE.y) / ROUTE_LENGTH_NM;
  const progress = Math.min(1, Math.max(0, along / ROUTE_LENGTH_NM));
  const crossTrackNm = Math.abs(p.x * ROUTE.y - p.y * ROUTE.x) / ROUTE_LENGTH_NM;

  // O destino é o terminal para onde a proa aponta
  const offset = Math.abs(((((headingDeg - ROUTE_BEARING) % 360) + 540) % 360) - 180);
  const toItaparica = offset <= 90;
  const remainingNm = (toItaparica ? 1 - progress : progress) * ROUTE_LENGTH_NM;

  return {
    progress,
    destination: toItaparica ? BOM_DESPACHO : SAO_JOAQUIM,
    remainingNm,
    etaMinutes: speedKnots >= 1 ? (remainingNm / speedKnots) * 60 : null,
    crossTrackNm,
  };
}
