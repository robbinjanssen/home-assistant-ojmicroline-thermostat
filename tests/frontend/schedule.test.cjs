// Run with: node --test tests/frontend/schedule.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let Card;
const context = {
  HTMLElement: class {},
  window: {},
  customElements: { get() {}, define(_name, cls) { Card = cls; } },
  Intl, Date, Set,
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../custom_components/ojmicroline_thermostat/frontend/ojmicroline-schedule-card.js'), 'utf8'), context);

function card(unit = '°F') {
  const instance = Object.create(Card.prototype);
  instance._config = { entity: 'sensor.floor_schedule', climate_entity: 'climate.floor' };
  instance._hass = {
    config: { unit_system: { temperature: unit } },
    locale: { language: 'en' },
    states: { 'sensor.floor_schedule': { attributes: {
      monday: [{ time: '06:00', temperature: 22.22 }, { time: '22:00', temperature: 17.77 }],
      same_day_only: true,
    } } },
  };
  instance._render = () => {};
  return instance;
}

test('Fahrenheit display and unchanged draft preserve centidegrees', () => {
  const instance = card();
  assert.equal(instance._formatTemperature(17.77), '64°');
  instance._startEdit(0);
  assert.equal(instance._draft.events[0].temperature, 72);
  assert.equal(instance._draft.events[1].temperature, 64);
  assert.equal(instance._serviceTemperature(instance._draft.events[0]), 22.22);
  assert.equal(instance._serviceTemperature(instance._draft.events[1]), 17.77);
  assert.match(instance._editorHtml(instance._texts()), /°F/);
  assert.match(instance._editorHtml(instance._texts()), /same day/);
});

test('changed Fahrenheit input is converted to Celsius for the service', () => {
  const instance = card();
  instance._startEdit(0);
  instance._draft.events[1].temperature = '65';
  assert.ok(Math.abs(instance._serviceTemperature(instance._draft.events[1]) - 18.3333333) < 0.00001);
});

test('Celsius users retain Celsius editing', () => {
  const instance = card('°C');
  instance._startEdit(0);
  assert.equal(instance._draft.events[0].temperature, 22.22);
  instance._draft.events[0].temperature = '23';
  assert.equal(instance._serviceTemperature(instance._draft.events[0]), 23);
  assert.match(instance._editorHtml(instance._texts()), /°C/);
});

test('saving sends selected weekdays and preserves untouched temperatures', async () => {
  const instance = card();
  let saved;
  instance._hass.callService = async (...args) => { saved = args; };
  instance._startEdit(0);
  instance._draft.days.add(6);
  await instance._save();
  assert.equal(saved[1], 'set_schedule');
  assert.equal(JSON.stringify(saved[2].days), JSON.stringify(['monday', 'sunday']));
  assert.equal(saved[2].events[1].temperature, 17.77);
  assert.equal(instance._draft, null);
});
