// Adaptador da API REST da Central (SCRUM-22), servida pelo Nginx em /api.
//   GET /api/telemetry/latest              -> último registro (por embarcação)
//   GET /api/telemetry/history?limit=N     -> registros em ordem qualquer
// Os campos seguem as colunas da tabela `telemetria` (src/database/models.py).
// Se o contrato final da SCRUM-22 mudar, este é o único arquivo a ajustar.

export interface CentralTelemetryRow {
  packet_id: string;
  boat_id: string;
  sequence_number?: number;
  /** ISO 8601 (DateTime com timezone) */
  timestamp: string;
  latitude: number;
  longitude: number;
  speed_knots?: number | null;
  course_heading?: number | null;
  engine_rpm?: number | null;
  engine_temp_celsius?: number | null;
  fuel_level_percent?: number | null;
  battery_voltage?: number | null;
  network_latency_ms?: number | null;
}

/** Ponto de telemetria normalizado para o dashboard. */
export interface TelemetryPoint {
  id: string;
  boatId: string;
  time: number;
  latitude: number;
  longitude: number;
  speedKnots: number | null;
  heading: number | null;
  rpm: number | null;
  engineTempC: number | null;
  fuelPercent: number | null;
  batteryV: number | null;
}

export function toPoint(row: CentralTelemetryRow): TelemetryPoint {
  return {
    id: row.packet_id,
    boatId: row.boat_id,
    time: Date.parse(row.timestamp),
    latitude: row.latitude,
    longitude: row.longitude,
    speedKnots: row.speed_knots ?? null,
    heading: row.course_heading ?? null,
    rpm: row.engine_rpm ?? null,
    engineTempC: row.engine_temp_celsius ?? null,
    fuelPercent: row.fuel_level_percent ?? null,
    batteryV: row.battery_voltage ?? null,
  };
}

/** Aceita lista pura, envelope { items } / { data } ou objeto único. */
export function unwrapRows(body: unknown): CentralTelemetryRow[] {
  if (Array.isArray(body)) return body as CentralTelemetryRow[];
  if (body && typeof body === 'object') {
    const envelope = body as { items?: unknown; data?: unknown };
    if (Array.isArray(envelope.items)) return envelope.items as CentralTelemetryRow[];
    if (Array.isArray(envelope.data)) return envelope.data as CentralTelemetryRow[];
    if ('packet_id' in body) return [body as CentralTelemetryRow];
  }
  return [];
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number | null };

async function getRows(path: string, signal: AbortSignal): Promise<ApiResult<TelemetryPoint[]>> {
  try {
    const response = await fetch(path, { cache: 'no-store', signal });
    if (response.status === 404) return { ok: true, data: [] };
    if (!response.ok) return { ok: false, status: response.status };
    const points = unwrapRows(await response.json())
      .map(toPoint)
      .filter((point) => Number.isFinite(point.time))
      .sort((a, b) => a.time - b.time);
    return { ok: true, data: points };
  } catch {
    return { ok: false, status: null };
  }
}

export const fetchLatest = (signal: AbortSignal) => getRows('/api/telemetry/latest', signal);

export const fetchHistory = (limit: number, signal: AbortSignal) =>
  getRows(`/api/telemetry/history?limit=${limit}`, signal);
