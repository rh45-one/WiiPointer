export const STORAGE_KEY = 'wiipointer.design-lab.v1';
export const BUTTONS = ['A', 'B', 'HOME', 'Right', 'Left', 'Up', 'Down', '+', '−', '1', '2'];
export const ACTIONS = ['Left click', 'Right click', 'Hold to aim', 'Recalibrate', 'Next slide', 'Previous slide', 'Scroll up', 'Scroll down', 'Start presentation', 'Exit presentation', 'Black screen', 'Play / pause', 'Keyboard shortcut', 'Unassigned'];

export function freshSettings() {
  return {
    pointer: { sensitivity: 12, vertical: 12, linked: true, smoothing: 25, deadzone: 0.3,
      acceleration: true, strength: 0.3, start: 5, end: 60, roll: true,
      invertX: true, invertY: false, activation: 'Hold' },
    buttons: { A: 'Left click', B: 'Hold to aim', HOME: 'Recalibrate', Right: 'Next slide',
      Left: 'Previous slide', Up: 'Scroll up', Down: 'Scroll down', '+': 'Start presentation',
      '−': 'Exit presentation', '1': 'Black screen', '2': 'Unassigned' },
    shortcuts: Object.fromEntries(BUTTONS.map(key => [key, ''])),
    lights: { pattern: 'player', player: 1, mask: [true, false, false, false], speed: 1.8, quiet: false },
    general: { autoStart: true, recovery: true, calibrate: true, minimized: true,
      notifications: true, sound: false, motion: 'System', contrast: false, textSize: 100, appearance: 'System' },
  };
}

export const BUILTINS = [
  { name: 'Presentation', description: 'Steady aiming, familiar slide controls.', icon: 'slides' },
  { name: 'Everyday', description: 'A little more pace for your desktop.', icon: 'pointer' },
  { name: 'Precision', description: 'Fine adjustments with a quieter response.', icon: 'target' },
];

export function preset(name) {
  const settings = freshSettings();
  if (name === 'Everyday') {
    Object.assign(settings.pointer, { sensitivity: 15, vertical: 15, strength: 0.35, smoothing: 20 });
    settings.buttons.Right = 'Scroll down';
    settings.buttons.Left = 'Scroll up';
  }
  if (name === 'Precision') {
    Object.assign(settings.pointer, { sensitivity: 8, vertical: 8, strength: 0.15, smoothing: 35 });
  }
  return settings;
}

export function freshModel() {
  return { version: 1, settings: freshSettings(), activeProfile: 'Presentation', profiles: [], lastCalibration: null };
}

const numberRules = {
  sensitivity: [4, 30], vertical: [4, 30], smoothing: [0, 100], deadzone: [0, 2],
  strength: [0, 1], start: [0, 20], end: [25, 160], player: [1, 4], speed: [0.6, 4], textSize: [100, 125],
};
const choices = {
  activation: ['Hold', 'Toggle', 'Always on'], pattern: ['player', 'custom', 'all', 'blink', 'wave', 'off'],
  motion: ['System', 'Reduced', 'Full'], appearance: ['System', 'Light', 'Dark'],
};

export function validateSettings(input) {
  const result = freshSettings();
  for (const [section, defaults] of Object.entries(result)) {
    if (!input?.[section] || typeof input[section] !== 'object') throw new Error(`Missing ${section} settings.`);
    for (const [key, fallback] of Object.entries(defaults)) {
      const value = input[section][key];
      if (section === 'buttons') {
        if (!ACTIONS.includes(value)) throw new Error(`Unknown action for ${key}.`);
      } else if (section === 'shortcuts') {
        if (typeof value !== 'string' || value.length > 48 || /[\u0000-\u001f\u007f]/.test(value)) throw new Error(`Invalid shortcut for ${key}.`);
      } else if (key === 'mask') {
        if (!Array.isArray(value) || value.length !== 4 || value.some(v => typeof v !== 'boolean')) throw new Error('Invalid player lights.');
      } else if (typeof fallback === 'boolean') {
        if (typeof value !== 'boolean') throw new Error(`Invalid ${key}.`);
      } else if (typeof fallback === 'number') {
        const [min, max] = numberRules[key];
        if (!Number.isFinite(value) || value < min || value > max) throw new Error(`${key} is out of range.`);
        if (key === 'player' && !Number.isInteger(value)) throw new Error('Player number must be a whole number.');
      } else if (!choices[key]?.includes(value)) throw new Error(`Invalid ${key}.`);
      result[section][key] = Array.isArray(value) ? [...value] : value;
    }
  }
  if (result.pointer.end <= result.pointer.start) throw new Error('Fast-sweep threshold must exceed the starting threshold.');
  return result;
}

export function validateModel(input) {
  if (input?.version !== 1) throw new Error('This is not a WiiPointer design-preview settings file.');
  const model = freshModel();
  model.settings = validateSettings(input.settings);
  if (!Array.isArray(input.profiles) || input.profiles.length > 8) throw new Error('Use at most eight custom profiles.');
  const names = new Set(BUILTINS.map(p => p.name.toLowerCase()));
  model.profiles = input.profiles.map(profile => {
    const name = typeof profile.name === 'string' ? profile.name.trim() : '';
    if (!name || name.length > 32 || names.has(name.toLowerCase())) throw new Error('Profile names must be unique and at most 32 characters.');
    names.add(name.toLowerCase());
    return { name, settings: validateSettings(profile.settings) };
  });
  const available = [...BUILTINS, ...model.profiles].map(p => p.name);
  model.activeProfile = available.includes(input.activeProfile) ? input.activeProfile : 'Presentation';
  if (typeof input.lastCalibration === 'number' && Number.isFinite(input.lastCalibration)) model.lastCalibration = input.lastCalibration;
  return model;
}

export function gain(speed, pointer) {
  if (!pointer.acceleration) return 1;
  const x = Math.min(1, Math.max(0, (speed - pointer.start) / (pointer.end - pointer.start)));
  return 1 + pointer.strength * (2 * x * x * (3 - 2 * x) - 0.5);
}

export function curvePoints(pointer) {
  return Array.from({ length: 61 }, (_, i) => `${28 + i * 5},${155 - gain(i * 2, pointer) * 44}`).join(' ');
}

export function calibrationFrame(elapsed, stableSince = 5) {
  if (elapsed < 5) return { phase: 'settling', remaining: Math.ceil(5 - elapsed), progress: elapsed / 10,
    lights: Array.from({ length: 4 }, (_, i) => i < Math.ceil(4 * (1 - elapsed / 5))) };
  if (elapsed - stableSince >= 5 && elapsed <= 30) return { phase: 'complete', remaining: 0, progress: 1, lights: [true, false, false, false] };
  if (elapsed >= 30) return { phase: 'failed', remaining: 0, progress: 0, lights: [true, false, false, false] };
  const active = [0, 1, 2, 3, 2, 1][Math.floor((elapsed - 5) / 0.1) % 6];
  return { phase: 'measuring', remaining: Math.max(0, Math.ceil(5 - (elapsed - stableSince))),
    progress: Math.min(0.99, (5 + Math.max(0, elapsed - stableSince)) / 10),
    lights: [0, 1, 2, 3].map(i => i === active) };
}

export function idleLights(settings, seconds, presentation = false, reduced = false) {
  const light = settings.lights;
  if (light.pattern === 'off') return [false, false, false, false];
  if (presentation && light.quiet) return [0, 1, 2, 3].map(i => i === light.player - 1);
  if (light.pattern === 'all') return [true, true, true, true];
  if (light.pattern === 'custom') return [...light.mask];
  if (light.pattern === 'blink' && !reduced) return [0, 1, 2, 3].map(i => i === light.player - 1 && seconds % light.speed < light.speed / 2);
  if (light.pattern === 'wave' && !reduced) {
    const active = [0, 1, 2, 3, 2, 1][Math.floor(seconds / (light.speed / 6)) % 6];
    return [0, 1, 2, 3].map(i => i === active);
  }
  return [0, 1, 2, 3].map(i => i === light.player - 1);
}
