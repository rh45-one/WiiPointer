import test from 'node:test';
import assert from 'node:assert/strict';
import { freshSettings, freshModel, validateModel, validateSettings, preset, gain, curvePoints, calibrationFrame, idleLights } from './model.mjs';

test('default acceleration matches the daemon and can be disabled', () => {
  const pointer = freshSettings().pointer;
  assert.equal(gain(0, pointer), .85);
  assert.equal(gain(60, pointer), 1.45);
  let previous = 0;
  for (let speed = 0; speed <= 200; speed++) {
    const current = gain(speed, pointer);
    assert.ok(current >= previous && current >= .85 && current <= 1.45);
    previous = current;
  }
  pointer.acceleration = false;
  assert.equal(gain(0, pointer), 1);
  assert.equal(gain(120, pointer), 1);
});

test('all supported acceleration strengths fit the curve preview', () => {
  const pointer = freshSettings().pointer;
  pointer.strength = 1;
  for (const point of curvePoints(pointer).split(' ')) {
    const [x, y] = point.split(',').map(Number);
    assert.ok(x >= 28 && x <= 328 && y >= 24 && y <= 156);
  }
});

test('calibration counts down, measures, completes, and waits after movement', () => {
  assert.deepEqual(calibrationFrame(0).lights, [true, true, true, true]);
  assert.deepEqual(calibrationFrame(1.3).lights, [true, true, true, false]);
  assert.deepEqual(calibrationFrame(2.6).lights, [true, true, false, false]);
  assert.deepEqual(calibrationFrame(3.9).lights, [true, false, false, false]);
  assert.equal(calibrationFrame(5).phase, 'measuring');
  assert.equal(calibrationFrame(10).phase, 'complete');
  assert.equal(calibrationFrame(10, 8).phase, 'measuring');
  assert.equal(calibrationFrame(13, 8).phase, 'complete');
  assert.equal(calibrationFrame(30, 29).phase, 'failed');
});

test('idle lights are binary, customisable, and respect quiet/reduced modes', () => {
  const settings = freshSettings();
  assert.deepEqual(idleLights(settings, 0), [true, false, false, false]);
  settings.lights.pattern = 'custom'; settings.lights.mask = [false, true, false, true];
  assert.deepEqual(idleLights(settings, 0), settings.lights.mask);
  settings.lights.pattern = 'wave';
  assert.notDeepEqual(idleLights(settings, 0), idleLights(settings, .4));
  assert.deepEqual(idleLights(settings, .4, false, true), [true, false, false, false]);
  settings.lights.quiet = true;
  assert.deepEqual(idleLights(settings, .4, true), [true, false, false, false]);
  settings.lights.pattern = 'off';
  assert.deepEqual(idleLights(settings, .4), [false, false, false, false]);
});

test('settings round-trip without sharing references or unexpected properties', () => {
  const original = freshModel();
  original.profiles.push({ name: 'My slides', settings: preset('Precision') });
  original.activeProfile = 'My slides';
  const clone = validateModel(JSON.parse(JSON.stringify(original)));
  assert.deepEqual(clone, original);
  clone.settings.lights.mask[0] = false;
  assert.equal(original.settings.lights.mask[0], true);
  const input = JSON.parse(JSON.stringify(freshModel()));
  input.settings.pointer.surprise = 'ignored';
  assert.equal(validateModel(input).settings.pointer.surprise, undefined);
});

test('malformed files, ranges, duplicate names, and wrong action enums are rejected', () => {
  assert.throws(() => validateModel({ version: 3 }));
  for (const mutate of [
    s => { s.pointer.sensitivity = Infinity; }, s => { s.pointer.strength = -1; },
    s => { s.pointer.end = 1; }, s => { s.lights.mask = [true]; },
    s => { s.buttons.A = 'Run shell command'; }, s => { s.general.sound = 'true'; },
    s => { s.lights.player = 1.5; },
    s => { s.shortcuts.A = 'x'.repeat(49); }, s => { s.shortcuts.B = 'Ctrl\nP'; },
  ]) {
    const settings = freshSettings(); mutate(settings);
    assert.throws(() => validateSettings(settings));
  }
  const duplicate = freshModel();
  duplicate.profiles.push({ name: 'presentation', settings: freshSettings() });
  assert.throws(() => validateModel(duplicate));
});
