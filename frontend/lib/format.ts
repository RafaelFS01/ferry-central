export function formatNumber(value: number | null, decimals = 0): string {
  if (value === null) return '—';
  return value.toLocaleString('pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function formatTime(epochMs: number): string {
  return new Date(epochMs).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function formatShortTime(epochMs: number): string {
  return new Date(epochMs).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

/** "agora", "há 12 s", "há 3 min" */
export function formatAge(fromEpochMs: number, nowMs: number): string {
  const seconds = Math.max(0, Math.round((nowMs - fromEpochMs) / 1000));
  if (seconds < 3) return 'agora';
  if (seconds < 60) return `há ${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `há ${minutes} min` : `há ${Math.floor(minutes / 60)} h`;
}

/** Posição em graus e minutos náuticos: 12°58,30′S · 038°33,51′W */
export function formatCoordinate(value: number, axis: 'lat' | 'lon'): string {
  const hemisphere = axis === 'lat' ? (value < 0 ? 'S' : 'N') : value < 0 ? 'W' : 'E';
  const absolute = Math.abs(value);
  const degrees = Math.floor(absolute);
  const minutes = formatNumber((absolute - degrees) * 60, 2).padStart(5, '0');
  return `${String(degrees).padStart(axis === 'lat' ? 2 : 3, '0')}°${minutes}′${hemisphere}`;
}

const CARDINALS = ['N', 'NE', 'L', 'SE', 'S', 'SO', 'O', 'NO'] as const;

export function cardinalOf(heading: number): string {
  return CARDINALS[Math.round((((heading % 360) + 360) % 360) / 45) % 8] ?? 'N';
}

export function boatName(boatId: string): string {
  return boatId.replace(/^ferry-/, '').split('-').map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}
