// Geografia da travessia Salvador–Itaparica na Baía de Todos-os-Santos.
// Coordenadas dos terminais iguais às do simulador do barco (ferry-boat/src/simulator/route.ts).

export interface Terminal {
  name: string;
  city: string;
  position: [number, number];
}

export const TERMINAL_SAO_JOAQUIM: Terminal = { name: 'Terminal São Joaquim', city: 'Salvador', position: [-12.9482, -38.5028] };
export const TERMINAL_BOM_DESPACHO: Terminal = { name: 'Terminal Bom Despacho', city: 'Itaparica', position: [-12.9774, -38.5724] };

export const TERMINALS = [TERMINAL_SAO_JOAQUIM, TERMINAL_BOM_DESPACHO] as const;

/** Rota nominal (ortodrômica) usada pelo simulador. */
export const NOMINAL_ROUTE: [number, number][] = [TERMINAL_SAO_JOAQUIM.position, TERMINAL_BOM_DESPACHO.position];

export const MAP_CENTER: [number, number] = [-12.9628, -38.5376];
export const MAP_ZOOM = 13;
