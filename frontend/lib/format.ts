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

export function boatName(boatId: string): string {
  return boatId.replace(/^ferry-/, '').split('-').map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}
