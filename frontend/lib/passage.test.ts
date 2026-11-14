import { test } from 'node:test';
import assert from 'node:assert/strict';
import { BOM_DESPACHO, passageOf, ROUTE_BEARING, ROUTE_LENGTH_NM, SAO_JOAQUIM } from './passage.ts';

const MIDPOINT = { lat: (SAO_JOAQUIM.lat + BOM_DESPACHO.lat) / 2, lon: (SAO_JOAQUIM.lon + BOM_DESPACHO.lon) / 2 };

test('saindo de São Joaquim com proa para Itaparica, resta a travessia inteira', () => {
  const passage = passageOf(SAO_JOAQUIM, ROUTE_BEARING, 12);
  assert.equal(passage.progress, 0);
  assert.equal(passage.destination, BOM_DESPACHO);
  assert.ok(Math.abs(passage.remainingNm - ROUTE_LENGTH_NM) < 1e-9);
});

test('no meio do caminho voltando para Salvador, o destino segue a proa e o ETA usa a velocidade', () => {
  const passage = passageOf(MIDPOINT, (ROUTE_BEARING + 180) % 360, 12);
  assert.ok(Math.abs(passage.progress - 0.5) < 0.01);
  assert.equal(passage.destination, SAO_JOAQUIM);
  assert.ok(Math.abs(passage.etaMinutes! - (passage.remainingNm / 12) * 60) < 1e-9);
  assert.ok(passage.crossTrackNm < 0.01);
});

test('parado não há ETA e posições além do terminal ficam limitadas à rota', () => {
  const beyond = { lat: BOM_DESPACHO.lat - 0.01, lon: BOM_DESPACHO.lon - 0.02 };
  const passage = passageOf(beyond, ROUTE_BEARING, 0.2);
  assert.equal(passage.progress, 1);
  assert.equal(passage.remainingNm, 0);
  assert.equal(passage.etaMinutes, null);
});
