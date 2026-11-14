import { test } from 'node:test';
import assert from 'node:assert/strict';
import { evaluateAlerts, type AlertInput } from './alerts.ts';

const NOW = 1_800_000_000_000;
const reading = (overrides: Partial<AlertInput> = {}): AlertInput =>
  ({ time: NOW, engineTempC: 80, batteryV: 26, fuelPercent: 80, ...overrides });

test('leitura nominal não gera alertas', () => {
  assert.deepEqual(evaluateAlerts(reading(), NOW), []);
});

test('temperatura acima de 90 °C é crítica; 88–90 °C é atenção', () => {
  assert.equal(evaluateAlerts(reading({ engineTempC: 90.5 }), NOW)[0]?.level, 'critical');
  assert.equal(evaluateAlerts(reading({ engineTempC: 90 }), NOW)[0]?.level, 'warning');
  assert.equal(evaluateAlerts(reading({ engineTempC: 87.9 }), NOW).length, 0);
});

test('silêncio acima de 30 s indica partição de rede', () => {
  const alerts = evaluateAlerts(reading({ time: NOW - 31_000 }), NOW);
  assert.deepEqual(alerts.map((alert) => alert.id), ['stale']);
});

test('alertas críticos vêm antes dos de atenção', () => {
  const alerts = evaluateAlerts(reading({ engineTempC: 95, fuelPercent: 5 }), NOW);
  assert.deepEqual(alerts.map((alert) => alert.level), ['critical', 'warning']);
});

test('sem leitura não há alertas', () => {
  assert.deepEqual(evaluateAlerts(null, NOW), []);
});
