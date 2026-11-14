import { STORAGE_KEY, BUTTONS, ACTIONS, BUILTINS, freshModel, freshSettings, preset, validateModel,
  gain, curvePoints, calibrationFrame, idleLights } from './model.mjs';

const style = document.documentElement.dataset.style;
const root = document.querySelector('#app');
const dialog = document.querySelector('#dialog');
const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let model = freshModel();
let storageAvailable = true;
let loadNotice = '';
try {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored) {
    try { model = validateModel(JSON.parse(stored)); }
    catch { loadNotice = 'Saved demo settings were invalid. Using safe defaults; real settings are untouched.'; }
  }
} catch { storageAvailable = false; loadNotice = 'Browser storage is unavailable. Changes will last for this tab only.'; }
const runtime = { page: 'home', mode: 'ready', paused: false, service: true, selectedButton: 'A',
  grip: 0, calibration: null, result: null, hits: 0, events: [], toastTimer: null, learn: false };
let svgId = 0;
let audio;
const navigation = [
  ['home', 'Home', 'home'], ['pointer', 'Pointer', 'pointer'], ['buttons', 'Buttons', 'buttons'],
  ['lights', 'Lights', 'lights'], ['calibration', 'Calibration', 'calibration'],
  ['profiles', 'Profiles', 'profiles'], ['settings', 'Settings', 'settings'],
];
const paths = {
  home: '<path d="m3 10 9-7 9 7v10H5V10m4 10v-7h6v7"/>',
  pointer: '<path d="m5 3 14 9-7 2-3 7z"/>',
  buttons: '<rect x="5" y="2" width="14" height="20" rx="4"/><path d="M9 7h6m-3-3v6"/><circle cx="12" cy="14" r="2"/><path d="M9 19h1m4 0h1"/>',
  lights: '<rect x="2" y="8" width="3" height="8" rx="1"/><rect x="8" y="8" width="3" height="8" rx="1"/><rect x="14" y="8" width="3" height="8" rx="1"/><rect x="20" y="8" width="2" height="8" rx="1"/>',
  calibration: '<circle cx="12" cy="12" r="8"/><path d="M12 1v6m0 10v6M1 12h6m10 0h6"/><circle cx="12" cy="12" r="2"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  profiles: '<rect x="3" y="3" width="14" height="15" rx="3"/><path d="M8 21h10a3 3 0 0 0 3-3V8M7 8h6m-6 5h4"/>',
  settings: '<path d="m10 3-1 3-3 1-3-1-1 4 3 2v3l-2 2 3 3 3-1 3 1 1 2 4-1v-3l2-2 3-1-1-4-3-1-1-3z"/><circle cx="12" cy="12" r="3"/>',
  bluetooth: '<path d="m7 7 10 10-5 5V2l5 5L7 17"/>',
  battery: '<rect x="2" y="6" width="18" height="12" rx="3"/><path d="M23 10v4M6 10v4m4-4v4m4-4v4"/>',
  check: '<path d="m5 12 4 4L20 5"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  back: '<path d="M20 12H4m6-6-6 6 6 6"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  play: '<path d="m7 4 13 8-13 8z"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 5m0 3v.1"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  reset: '<path d="M3 10a9 9 0 1 1 2 9M3 3v7h7"/>',
  slides: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M12 17v5m-5 0h10M7 8h10m-10 4h5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 10v7m0-11v.1"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
};
const icon = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.pointer}</svg>`;
const button = (label, action, cls = 'button', glyph = '') => `<button type="button" class="${cls}" data-action="${action}">${glyph ? icon(glyph) : ''}<span>${label}</span></button>`;
const leds = (context = 'idle', cls = '') => `<div class="player-lights ${cls}" data-led-context="${context}" aria-label="Simulated player lights">${[0, 1, 2, 3].map(i => `<span data-led="${i}" class="${i === 0 ? 'is-on' : ''}"></span>`).join('')}</div>`;

function remote(interactive = false, cls = '') {
  const id = `remote-${++svgId}`;
  const attrs = key => interactive ? `data-map-key="${escape(key)}" tabindex="0" role="button" aria-label="Map ${escape(key)} button" class="remote-key ${runtime.selectedButton === key ? 'selected' : ''}"` : 'class="remote-key"';
  return `<svg class="remote ${cls}" viewBox="0 0 176 442" role="${interactive ? 'group' : 'img'}" aria-label="Illustration of a Wii Remote Plus${interactive ? '; select a button to map it' : ''}">
    <defs>
      <linearGradient id="${id}-body" x1="0" x2="1"><stop stop-color="#fff"/><stop offset=".5" stop-color="#eef0f1"/><stop offset="1" stop-color="#dfe3e4"/></linearGradient>
      <linearGradient id="${id}-key" x2="0" y2="1"><stop stop-color="#fff"/><stop offset="1" stop-color="#e8edf0"/></linearGradient>
      <filter id="${id}-shadow" x="-40%" y="-20%" width="180%" height="140%"><feDropShadow dx="6" dy="16" stdDeviation="14" flood-color="#3a4a55" flood-opacity=".14"/></filter>
    </defs>
    <g filter="url(#${id}-shadow)">
      <path d="M50 14Q90 6 126 14l-4 372q0 17-14 19H60q-14-2-14-19L42 30q0-14 8-16" fill="url(#${id}-body)" stroke="#c7d0d6" stroke-width="1.2"/>
      <path d="M49 30q39-9 78 0" fill="none" stroke="white" stroke-width="2.5" opacity=".7"/>
      <path d="M64 15h48v4q0 2-2 4h-44q-2 0-2-4z" fill="#fff" stroke="#c7d0d6" stroke-width="1"/>
      <g ${attrs('POWER')}><circle cx="58" cy="52" r="8" fill="#f4f7f8" stroke="#d6dfe4" stroke-width="1.2"/><path d="M58 47v6m-3-3a4 4 0 1 0 6 0" stroke="#cd8c8c" fill="none" stroke-width="1.2"/></g>
      <path d="M64 73h48v10h-48z" fill="#f4f7f8" stroke="#c7d0d6" stroke-width="1"/>
      <text x="88" y="81" text-anchor="middle" fill="#7d8c95" font-size="8" font-family="sans-serif" letter-spacing=".4">SYNC</text>
      <path d="M62 96h52v20h-52z" fill="#e8f0f1" stroke="#c7d0d6" stroke-width="1"/>
      <g ${attrs('Up')}><rect x="76" y="100" width="24" height="12" rx="2" fill="transparent"/><path d="m82 110 3-3 3 3" stroke="#8c9da7" fill="none"/></g>
      <g ${attrs('Down')}><rect x="76" y="124" width="24" height="12" rx="2" fill="transparent"/><path d="m82 134 3 3 3-3" stroke="#8c9da7" fill="none"/></g>
      <g ${attrs('Left')}><rect x="62" y="108" width="12" height="24" rx="2" fill="transparent"/><path d="m72 118-3 3 3 3" stroke="#8c9da7" fill="none"/></g>
      <g ${attrs('Right')}><rect x="102" y="108" width="12" height="24" rx="2" fill="transparent"/><path d="m104 118 3 3-3 3" stroke="#8c9da7" fill="none"/></g>
      <g ${attrs('A')}><circle cx="88" cy="163" r="20" fill="url(#${id}-key)" stroke="#c7d0d6" stroke-width="1.4"/><text x="88" y="170" text-anchor="middle" fill="#7a8c96" font-size="20" font-family="sans-serif">A</text></g>
      <g ${attrs('−')}><circle cx="61" cy="219" r="9" fill="url(#${id}-key)" stroke="#c7d0d6"/><text x="61" y="223" text-anchor="middle" fill="#8596a2" font-size="13">−</text></g>
      <g ${attrs('HOME')}><circle cx="88" cy="219" r="9" fill="#eef6f8" stroke="#bcd6e0"/><path d="m83 219 5-4 5 4v4h-10z" fill="none" stroke="#7da7c1"/><text x="88" y="238" text-anchor="middle" fill="#9aa9b2" font-size="6" font-family="sans-serif" letter-spacing=".3">HOME</text></g>
      <g ${attrs('+')}><circle cx="115" cy="219" r="9" fill="url(#${id}-key)" stroke="#c7d0d6"/><text x="115" y="223" text-anchor="middle" fill="#8596a2" font-size="13">+</text></g>
      <g fill="#bcc9d2">${[0,1,2].map(r => [0,1,2,3].map(c => `<circle cx="${74+c*13}" cy="${264+r*9}" r="1.3"/>`).join('')).join('')}</g>
      <g ${attrs('1')}><circle cx="88" cy="303" r="11" fill="url(#${id}-key)" stroke="#c7d0d6"/><text x="88" y="308" text-anchor="middle" fill="#8596a2" font-size="13">1</text></g>
      <g ${attrs('2')}><circle cx="88" cy="337" r="11" fill="url(#${id}-key)" stroke="#c7d0d6"/><text x="88" y="342" text-anchor="middle" fill="#8596a2" font-size="13">2</text></g>
      <text x="88" y="374" text-anchor="middle" fill="#7a8c96" font-size="7" font-family="sans-serif" letter-spacing=".6">MotionPlus INSIDE</text>
      <text x="88" y="398" text-anchor="middle" fill="#b7c4cd" font-size="9" font-family="sans-serif" letter-spacing="1">Wii</text>
      <g data-led-context="idle">${[0,1,2,3].map(i => `<rect data-led="${i}" class="remote-led ${i === 0 ? 'is-on' : ''}" x="${60+i*14}" y="404" width="8" height="3" rx="1"/>`).join('')}</g>
    </g>
    ${interactive ? `<g ${attrs('B')}><rect x="140" y="140" width="32" height="30" rx="11" fill="#e8f6fe" stroke="#93cce9"/><text x="156" y="160" text-anchor="middle" fill="#3482ad" font-family="sans-serif" font-size="14">B</text><path d="M140 156h-7" stroke="#93cce9"/></g><text x="158" y="185" text-anchor="middle" fill="currentColor" font-size="7">on back</text>` : ''}
  </svg>`;
}

function get(path) { const [section, key] = path.split('.'); return model.settings[section][key]; }
function format(path) {
  const value = get(path);
  if (path.endsWith('sensitivity') || path.endsWith('vertical')) return `${Number(value).toFixed(1).replace('.0', '')} px/°`;
  if (path.endsWith('smoothing')) return `${value} ms`;
  if (path.endsWith('strength')) return `${Math.round(value * 100)}%`;
  if (path.endsWith('deadzone') || path.endsWith('start') || path.endsWith('end')) return `${value} °/s`;
  if (path.endsWith('speed')) return `${Number(value).toFixed(1)} s`;
  return String(value);
}
function range(path, label, min, max, step, help = '', disabled = false) {
  const id = path.replace('.', '-');
  return `<div class="range-control ${disabled ? 'is-disabled' : ''}"><div class="control-label"><label for="${id}">${label}</label><output for="${id}" data-output="${path}">${format(path)}</output></div>${help ? `<p class="control-help" id="${id}-help">${help}</p>` : ''}<input id="${id}" type="range" min="${min}" max="${max}" step="${step}" value="${get(path)}" style="--range-progress:${100 * (get(path) - min) / (max - min)}%" aria-valuetext="${format(path)}" data-setting="${path}" ${help ? `aria-describedby="${id}-help"` : ''} ${disabled ? 'disabled' : ''}><div class="range-ends"><span>${path.endsWith('speed') ? 'Lively' : min === 0 ? 'Less' : 'Gentle'}</span><span>${path.endsWith('speed') ? 'Unhurried' : 'More'}</span></div></div>`;
}
function toggle(path, label, description = '') {
  return `<label class="toggle-row" for="${path.replace('.', '-')}"><span><strong>${label}</strong>${description ? `<small>${description}</small>` : ''}</span><span class="switch"><input id="${path.replace('.', '-')}" type="checkbox" role="switch" data-setting="${path}" ${get(path) ? 'checked' : ''}><span class="switch-track"></span></span></label>`;
}
function selectControl(path, label, options, help = '') {
  const id = path.replace('.', '-');
  return `<div class="select-control"><label for="${id}">${label}</label><select id="${id}" data-setting="${path}">${options.map(option => `<option ${get(path) === option ? 'selected' : ''}>${escape(option)}</option>`).join('')}</select>${help ? `<p class="control-help">${help}</p>` : ''}</div>`;
}
function pageHead(kicker, title, description, action = '') {
  return `<div class="page-heading"><div><p class="eyebrow">${kicker}</p><h1 tabindex="-1">${title}</h1><p>${description}</p></div>${action}</div>`;
}
function panel(title, subtitle, content, cls = '') {
  return `<section class="panel ${cls}"><header class="panel-heading"><h2>${title}</h2>${subtitle ? `<p>${subtitle}</p>` : ''}</header>${content}</section>`;
}
function record(message) { runtime.events.unshift({ time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), message }); runtime.events.length = Math.min(runtime.events.length, 20); }
function notify(message) {
  const toast = document.querySelector('#toast');
  toast.textContent = message; toast.classList.add('visible');
  clearTimeout(runtime.toastTimer); runtime.toastTimer = setTimeout(() => toast.classList.remove('visible'), 4200);
}
function save() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(model)); }
  catch { if (storageAvailable) notify('Browser storage is unavailable. Changes will last for this tab only.'); storageAvailable = false; }
}
function applyAppearance() {
  const g = model.settings.general;
  const dark = g.appearance === 'Dark' || (g.appearance === 'System' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.appearance = dark ? 'dark' : 'light';
  document.documentElement.dataset.motion = g.motion === 'Reduced' || (g.motion === 'System' && matchMedia('(prefers-reduced-motion: reduce)').matches) ? 'reduced' : 'full';
  document.documentElement.dataset.contrast = g.contrast ? 'more' : 'normal';
  document.documentElement.dataset.crt = g.crt ? 'on' : 'off';
  document.documentElement.style.fontSize = `${g.textSize}%`;
}
function status() {
  if (runtime.mode === 'disconnected') return ['disconnected', 'Waiting for your remote', 'Press A to reconnect · demo state'];
  if (runtime.mode === 'permission') return ['warning', 'A little help needed', 'Input permission required · demo state'];
  if (runtime.calibration) return ['calibrating', 'Finding your steady', 'Keep the remote still · simulated calibration'];
  if (!runtime.service) return ['paused', 'Service stopped', 'Start the demo service to try the pointer'];
  if (runtime.paused) return ['paused', 'Taking a little pause', 'Your settings are right where you left them'];
  if (runtime.mode === 'low') return ['warning', 'Ready · battery low', '18% battery · simulated device'];
  return ['ready', 'Ready to point', 'Hold B to aim. Release to rest.'];
}
function profileModified() {
  const original = model.profiles.find(p => p.name === model.activeProfile)?.settings || preset(model.activeProfile);
  return JSON.stringify(original) !== JSON.stringify(model.settings);
}
function chrome(content) {
  const [kind, label] = status();
  return `<div class="lab-bar"><a href="./index.html" class="lab-brand">${icon('back')} Design lab</a><div class="design-switch" aria-label="Compare designs"><a href="./original.html#${runtime.page}" ${style === 'original' ? 'aria-current="page"' : ''}>Original Wii</a><a href="./neo.html#${runtime.page}" ${style === 'neo' ? 'aria-current="page"' : ''}>Neo Wii</a></div><span class="lab-note"><span class="demo-dot"></span> Interactive demo · no hardware connection</span></div>
  <div class="app-shell"><header class="app-header"><a class="brand" href="#home"><img src="./mark.svg" alt="" width="36" height="36"><span>Wii<span class="brand-light">Pointer</span><small>${style === 'original' ? 'WiiPointer Menu' : 'A familiar kind of freedom'}</small></span></a><div class="header-right"><span class="status-pill ${kind}"><span></span>${label}</span>${button(runtime.paused ? 'Resume demo' : 'Pause demo', 'pause', 'button quiet compact', runtime.paused ? 'play' : 'pause')}${button('Help', 'help', 'button icon-button', 'help')}</div></header>
  <div class="workspace"><nav class="main-nav" aria-label="Main navigation">${navigation.map(([page, name, glyph]) => `<a href="#${page}" ${runtime.page === page ? 'aria-current="page"' : ''}>${icon(glyph)}<span>${name}</span>${runtime.page === page ? '<i></i>' : ''}</a>`).join('')}<div class="nav-bottom"><span class="tiny-leds">${leds()}</span><span>Player ${model.settings.lights.player}<small>Demo remote · ${runtime.mode === 'low' ? '18' : '82'}% battery</small></span></div></nav><main id="main" class="main-content" data-page="${runtime.page}" tabindex="-1">${content}</main></div>
  <footer class="app-footer"><a class="wii-menu-button" href="#home" aria-label="WiiPointer home">Wii</a><span class="footer-profile">${icon('profiles')} <span data-profile-label>${escape(model.activeProfile)}${profileModified() ? ' · Modified' : ''}</span></span>${style === 'original' ? `<button type="button" class="button crt-switch" data-action="crt" aria-pressed="${model.settings.general.crt}" title="Static scanlines and a soft screen-edge vignette; no flicker">CRT texture <span>${model.settings.general.crt ? 'On' : 'Off'}</span></button>` : ''}<span class="footer-save">${icon('check')} ${storageAvailable ? 'Saved in this browser' : 'This tab only'} <span>· demo settings</span></span><label class="state-picker">Preview state <select id="preview-state"><option value="ready" ${runtime.mode === 'ready' ? 'selected' : ''}>Connected</option><option value="disconnected" ${runtime.mode === 'disconnected' ? 'selected' : ''}>Disconnected</option><option value="low" ${runtime.mode === 'low' ? 'selected' : ''}>Low battery</option><option value="permission" ${runtime.mode === 'permission' ? 'selected' : ''}>Permission needed</option></select></label></footer></div>`;
}

function channelArt(page) {
  if (page === 'pointer') return `<div class="tile-pointer"><span class="tile-target"></span>${icon('pointer')}<i></i></div>`;
  if (page === 'buttons') return `<div class="tile-buttons"><span>+</span><span>A</span><span>B</span></div>`;
  if (page === 'lights') return `<div class="tile-lights">${leds()}</div>`;
  if (page === 'calibration') return `<div class="tile-calibration">${icon('calibration')}<i></i><i></i></div>`;
  if (page === 'profiles') return `<div class="tile-profiles"><span>${icon('slides')}</span><span>${icon('pointer')}</span><span>${icon('target')}</span></div>`;
  return `<div class="tile-settings">${icon('settings')}<span>${icon('settings')}</span></div>`;
}
function clockText() {
  const now = new Date();
  return { time: now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }),
    date: now.toLocaleDateString([], { weekday: 'short', month: 'numeric', day: 'numeric' }), iso: now.toISOString() };
}
function originalHome(kind, label, hint) {
  const clock = clockText();
  return `<section class="classic-welcome"><h1 tabindex="-1">WiiPointer Menu</h1><div class="classic-device">${icon('bluetooth')}<span>Wii Remote Plus<small>${escape(hint)}</small></span>${icon('battery')}</div></section>
    <div class="channel-grid" aria-label="WiiPointer channels">
      ${navigation.slice(1).map(([page, name]) => `<a class="channel channel-${page}" href="#${page}"><div class="channel-preview">${channelArt(page)}</div><div class="channel-label"><span>${name}</span></div></a>`).join('')}
      ${Array.from({ length: 6 }, () => '<div class="channel channel-empty" aria-hidden="true"><span class="empty-channel-mark">Wii</span></div>').join('')}
    </div>
    <div class="classic-bottom"><span class="status-line ${kind}"><i></i>${label}</span><div class="classic-clock"><time data-clock-time datetime="${clock.iso}">${escape(clock.time)}</time><span data-clock-date>${escape(clock.date)}</span></div>${button('Calibration', 'calibrate-page', 'button quiet', 'calibration')}</div>`;
}
function home() {
  const [kind, label, hint] = status();
  if (style === 'original') return originalHome(kind, label, hint);
  return `<section class="neo-hero"><div class="hero-copy"><p class="eyebrow">DESIGN LAB</p><h1 tabindex="-1">WiiPointer design preview</h1><p>Two designs. Same controls. Try them both.</p><div class="hero-actions"><a class="button primary" href="#pointer">Pointer settings ${icon('arrow')}</a><a class="button quiet" href="#buttons">Button map ${icon('arrow')}</a></div><div class="hero-status ${kind}"><span class="status-orb">${icon(kind === 'ready' ? 'check' : kind === 'disconnected' ? 'bluetooth' : 'info')}</span><span><strong>${label}</strong><small>${hint}</small></span>${kind === 'disconnected' ? button('Reconnect demo', 'connect', 'button quiet compact') : ''}</div></div><div class="remote-stage"><div class="stage-halo"></div><div class="stage-ring ring-one"></div><div class="stage-ring ring-two"></div><span class="stage-chip chip-motion">${icon('pointer')} MotionPlus inside</span>${remote(false, 'hero-remote')}<span class="stage-chip chip-battery">${icon('battery')} ${runtime.mode === 'low' ? '18' : '82'}% <small>demo</small></span><span class="stage-caption">Wii Remote Plus <span>PLAYER ${model.settings.lights.player}</span></span></div></section>
  <div class="quick-grid"><a class="quick-card" href="#pointer"><span class="quick-icon">${icon('pointer')}</span><span class="eyebrow">Pointer feel</span><h2>${model.settings.pointer.sensitivity} <small>px/°</small></h2><p>${model.settings.pointer.acceleration ? 'Gentle acceleration' : 'Direct, linear movement'}</p>${icon('arrow', 'quick-arrow')}</a><a class="quick-card" href="#profiles"><span class="quick-icon violet">${icon('profiles')}</span><span class="eyebrow">Current profile</span><h2>${escape(model.activeProfile)}</h2><p>${profileModified() ? 'A few personal touches added' : 'Default settings'}</p>${icon('arrow', 'quick-arrow')}</a><a class="quick-card" href="#calibration"><span class="quick-icon mint">${icon('calibration')}</span><span class="eyebrow">Calibration</span><h2>${model.lastCalibration ? 'Feeling steady' : 'Ready when you are'}</h2><p>${model.lastCalibration ? 'Last calibrated in this demo' : 'Set down. Recalibrate. Carry on.'}</p>${icon('arrow', 'quick-arrow')}</a></div>
  <section class="small-invitation"><div>${icon('lights')}<span>Player lights even at rest.<small>Choose the idle pattern your remote shows while connected.</small></span></div><a href="#lights" class="text-link">Change player lights ${icon('arrow')}</a></section>`;
}

function curve() {
  return `<svg class="curve" viewBox="0 0 360 190" role="img" aria-label="Preview of cursor gain from slow to fast rotation"><defs><linearGradient id="curve-fill" x2="0" y2="1"><stop stop-color="#29a9e7" stop-opacity=".18"/><stop offset="1" stop-color="#29a9e7" stop-opacity="0"/></linearGradient></defs><path class="curve-grid" d="M28 24v132h304M28 61h304M28 105h304M104 24v132m76-132v132m76-132v132"/><path class="linear-guide" d="M28 111h304"/><polygon data-curve-fill points="28,156 ${curvePoints(model.settings.pointer)} 328,156" fill="url(#curve-fill)"/><polyline data-curve points="${curvePoints(model.settings.pointer)}" fill="none" stroke="var(--blue)" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/><text x="28" y="178">Fine adjustments</text><text x="332" y="178" text-anchor="end">Fast sweeps</text></svg>`;
}
function playground() {
  const blocked = !runtime.service || runtime.paused || ['disconnected', 'permission'].includes(runtime.mode);
  return `<section class="panel playground-panel"><header class="panel-heading"><div><span class="eyebrow">Try your feel</span><h2>Pointer playground</h2></div><span class="tiny-pill">Browser simulation</span></header><p class="control-help">Move your mouse inside the pad. The blue dot previews your settings; it does not move your system cursor or use real gyro data.</p><div class="aim-pad ${blocked ? 'blocked' : ''}" id="aim-pad"><span class="aim-axis axis-x"></span><span class="aim-axis axis-y"></span><span class="aim-ring ring-large"></span><span class="aim-ring ring-small"></span><button type="button" class="aim-target" data-action="target" aria-label="Tap the practice target"><span></span></button><span class="aim-dot" id="aim-dot"></span><span class="pad-caption">${blocked ? 'Resume or reconnect the demo to try it' : 'Move gently. Then try a faster sweep.'}</span></div><div class="playground-stats"><span>Target taps <strong id="hit-count">${runtime.hits}</strong></span><span>Response gain <strong id="gain-value">1.00×</strong></span>${button('Centre dot', 'centre-dot', 'button quiet compact', 'target')}</div><div class="grip-control"><span>Try a sideways grip</span><div class="segmented" aria-label="Simulated remote roll">${[[0, 'Face up'], [-90, 'Left'], [90, 'Right']].map(([angle, name]) => `<button type="button" data-grip="${angle}" aria-pressed="${runtime.grip === angle}">${name}</button>`).join('')}</div></div><p class="control-help">${model.settings.pointer.roll ? 'Roll compensation keeps screen directions consistent.' : 'Roll compensation is off: sideways grips mix horizontal and vertical motion.'}</p></section>`;
}
function pointerPage() {
  const p = model.settings.pointer;
  return pageHead('POINTER SETTINGS', 'Pointer feel', 'Adjust how the cursor moves when you hold B.', button('Reset pointer', 'reset-pointer', 'button quiet', 'reset')) +
  `<div class="feel-presets" aria-label="Pointer feel presets">${[['Precision', 'Precise', 'Small, considered movements'], ['Presentation', 'Balanced', 'A familiar, comfortable middle'], ['Everyday', 'Quick', 'A little more room to roam']].map(([name, label, hint]) => `<button type="button" data-feel="${name}" class="feel-preset ${p.sensitivity === preset(name).pointer.sensitivity && p.strength === preset(name).pointer.strength ? 'selected' : ''}">${icon(name === 'Precision' ? 'target' : name === 'Presentation' ? 'pointer' : 'arrow')}<strong>${label}</strong><span>${hint}</span></button>`).join('')}</div>
  <div class="two-column"><div class="panel-stack">${panel('Cursor speed', 'Start here. You can always come back to the details.', range('pointer.sensitivity', p.linked ? 'Mouse sensitivity' : 'Horizontal sensitivity', 4, 30, 0.5, 'Cursor travel per nominal degree of remote rotation.') + toggle('pointer.linked', 'Link horizontal & vertical', 'Keep both directions feeling the same.') + (!p.linked ? range('pointer.vertical', 'Vertical sensitivity', 4, 30, 0.5) : '') + range('pointer.smoothing', 'Motion smoothing', 0, 100, 5, 'A little steadiness; too much can feel floaty.') + toggle('pointer.roll', 'Compensate for sideways holding', 'Keep aiming directions natural when you roll the remote.'))}
  ${panel('Mouse acceleration', 'Acceleration changes gain with rotation speed, not time held.', toggle('pointer.acceleration', 'Mouse acceleration', 'Finer slow movement, more reach on a fast sweep.') + curve() + range('pointer.strength', 'Acceleration strength', 0, 1, 0.05, 'Zero restores a direct, linear response.', !p.acceleration) + `<details class="advanced"><summary>Fine-tune the curve</summary>${range('pointer.start', 'Begin increasing gain at', 0, 20, 1, '', !p.acceleration)}${range('pointer.end', 'Reach full gain at', 25, 160, 5, '', !p.acceleration)}<p class="control-help">These thresholds are prototype controls. GNOME may add its own pointer acceleration.</p></details>`)}
  ${panel('More options', '', `<details class="advanced"><summary>Aiming, axes & noise</summary>${selectControl('pointer.activation', 'Aim activation', ['Hold', 'Toggle', 'Always on'], 'Hold is safest for a presentation. The aim button is assigned in Buttons.')}${toggle('pointer.invertX', 'Invert raw horizontal gyro axis', 'On matches this remote’s current face-up mapping.')}${toggle('pointer.invertY', 'Invert vertical movement')}${range('pointer.deadzone', 'Ignore tiny movements below', 0, 2, 0.1, 'Soft deadzone after gyro bias correction.')}</details>`)}
  </div><div class="sticky-column">${playground()}<div class="note-card">${icon('info')}<p>Your real pointer is safe.<br><span>This playground changes only a dot in this browser. Hardware feel will need a separate integration test.</span></p></div></div></div>`;
}

function mappedAction(key) {
  return model.settings.buttons[key] === 'Keyboard shortcut'
    ? model.settings.shortcuts[key] || 'Choose a shortcut below'
    : model.settings.buttons[key];
}
function mappingRow(key) {
  const index = BUTTONS.indexOf(key);
  const label = ({ Right: 'D-pad right', Left: 'D-pad left', Up: 'D-pad up', Down: 'D-pad down', HOME: 'HOME', B: 'B · back trigger' })[key] || `${escape(key)} button`;
  return `<div class="mapping-row ${runtime.selectedButton === key ? 'selected' : ''}" data-mapping-row="${escape(key)}"><button type="button" class="keycap" data-map-key="${escape(key)}" aria-label="Select ${escape(key)} button">${escape(key)}</button><label for="map-${index}">${label}</label><select id="map-${index}" data-map="${escape(key)}">${ACTIONS.map(action => `<option ${model.settings.buttons[key] === action ? 'selected' : ''}>${action}</option>`).join('')}</select>${model.settings.buttons[key] === 'Keyboard shortcut' ? `<div class="shortcut-control"><label for="shortcut-${index}">Shortcut for ${escape(key)}</label><input type="text" id="shortcut-${index}" data-shortcut="${escape(key)}" value="${escape(model.settings.shortcuts[key])}" maxlength="48" placeholder="e.g. Ctrl + Shift + P" autocomplete="off" spellcheck="false"><small>Type a shortcut name. This preview does not capture or send keystrokes.</small></div>` : ''}</div>`;
}
function buttonPage() {
  const b = model.settings.buttons;
  const missing = [];
  if (!Object.values(b).includes('Hold to aim')) missing.push('No hold-to-aim button is assigned.');
  if (!Object.values(b).includes('Left click')) missing.push('No left-click button is assigned.');
  return pageHead('BUTTON SETTINGS', 'Map buttons', 'Choose what each button does.', button('Restore button map', 'reset-buttons', 'button quiet', 'reset')) +
  `<div class="mapping-layout"><section class="panel remote-mapping"><span class="eyebrow">Wii Remote Plus</span>${remote(true)}<div class="mapped-button"><span class="keycap">${escape(runtime.selectedButton)}</span><span><small>Assigned action</small><strong id="mapped-action">${escape(mappedAction(runtime.selectedButton))}</strong></span></div>${button(runtime.learn ? 'Choose a button above…' : 'Try button selection', 'learn', 'button quiet', 'buttons')}<p class="control-help">Illustration only. Physical button detection is not connected.</p></section><section class="panel mapping-panel"><header class="panel-heading"><h2>Make every press count.</h2><p>Mouse, presentation, and a few useful extras.</p></header>${missing.length ? `<div class="inline-notice warning">${icon('info')}<span>${missing.join(' ')} You can still explore; nothing is applied to your remote.</span></div>` : ''}<div class="mapping-list">${BUTTONS.map(mappingRow).join('')}</div><div class="mapping-note">${icon('info')}<p>Hold-to-aim is a clutch, not a click. HOME measures stationary gyro bias; it doesn’t recover an absolute heading. The POWER button is managed by the remote and isn’t remapped here.</p></div></section></div>`;
}

function lightPage() {
  const l = model.settings.lights;
  const patterns = [['player', 'Player light', 'Your player number'], ['custom', 'Your combination', 'Pick exactly which lights stay on'], ['all', 'All together', 'All lights on'], ['blink', 'Slow blink', 'On-and-off rhythm'], ['wave', 'Gentle wave', 'A little movement at rest'], ['off', 'Lights out', 'Lights off']];
  return pageHead('PLAYER LIGHTS', 'Connected idle lights', 'Choose what the four player lights do while the remote is connected but not aiming.') +
  `<div class="two-column lights-layout"><div class="panel-stack">${panel('While your remote is resting', 'Connected-idle patterns only. Calibration keeps its own countdown and chase.', `<div class="pattern-grid">${patterns.map(([key, title, hint]) => `<button type="button" class="pattern-option ${l.pattern === key ? 'selected' : ''}" data-pattern="${key}" aria-pressed="${l.pattern === key}"><span class="pattern-dots pattern-${key}">${[0, 1, 2, 3].map(i => `<i class="${key === 'off' || ((key === 'player' || key === 'blink') && i > 0) || (key === 'custom' && i % 2) ? '' : 'on'}"></i>`).join('')}</span><strong>${title}</strong><small>${hint}</small>${l.pattern === key ? icon('check', 'pattern-check') : ''}</button>`).join('')}</div>`)}
  ${panel('A few personal touches', '', `<div class="control-label"><span>Your player number</span><span class="subtle">1–4</span></div><div class="player-picker" aria-label="Player number">${[1, 2, 3, 4].map(i => `<button type="button" data-player="${i}" aria-pressed="${l.player === i}">${i}</button>`).join('')}</div>${l.pattern === 'custom' ? `<div class="control-label"><span>Choose your lights</span></div><div class="custom-led-picker">${l.mask.map((on, i) => `<button type="button" data-light="${i}" aria-pressed="${on}" aria-label="Player light ${i + 1}"><i class="${on ? 'on' : ''}"></i><span>${i + 1}</span></button>`).join('')}</div>` : ''}${range('lights.speed', 'Animation pace · full cycle', 0.6, 4, 0.2, 'Only used for slow blink and gentle wave.', !['blink', 'wave'].includes(l.pattern))}${toggle('lights.quiet', 'Keep it steady in Presentation', 'Use a steady player light while the Presentation profile is active.')}`)}
  </div><div class="sticky-column"><section class="panel light-preview"><p class="eyebrow">Preview</p><h2>Looks good on you.</h2><div class="light-remote-stage">${remote()}</div>${leds('idle', 'large-lights')}<p data-light-description>${escape(patterns.find(p => p[0] === l.pattern)[1])}</p><span class="tiny-pill">Visual simulation only</span></section><div class="note-card">${icon('calibration')}<p>Calibration gets the spotlight.<br><span>Its countdown and fast chase always take priority. Your chosen idle pattern returns afterwards. Wii LEDs are on/off, not independently dimmable.</span></p></div>${l.quiet && model.activeProfile === 'Presentation' ? '<div class="inline-notice">Presentation quiet mode is showing a steady player light in this preview.</div>' : ''}</div></div>`;
}

function calibrationPage() {
  const running = Boolean(runtime.calibration);
  const success = runtime.result === 'complete';
  const failed = runtime.result === 'failed';
  return pageHead('CALIBRATION', 'Calibrate the gyro', 'Set the remote down and hold still. This measures the stationary bias so the pointer does not drift.') +
  `<section class="panel calibration-hero ${success ? 'cal-success' : ''} ${failed ? 'cal-failed' : ''}"><div class="calibration-orbit">${icon(success ? 'check' : failed ? 'info' : 'calibration')}<span></span><span></span></div><p class="eyebrow" id="cal-phase">${success ? 'A NICE, STEADY START' : failed ? 'LET’S GIVE THAT ANOTHER GO' : running ? 'FINDING YOUR STEADY' : 'SET DOWN. HANDS OFF. READY.'}</p><h2 id="cal-title">${success ? 'All steady.' : failed ? 'Not quite still enough.' : running ? 'Let it settle.' : 'Let’s find your steady.'}</h2><p id="cal-description">${success ? 'The simulated measurement was accepted. Your real calibration has not changed.' : failed ? 'The demo retained its previous calibration. Try a stable surface and keep your hands clear.' : 'Rest the remote on a stable surface. We’ll give you five seconds before the measurement begins.'}</p>${leds('calibration', 'calibration-lights')}<div class="cal-progress"><progress id="cal-progress" max="1" value="${success ? 1 : 0}" aria-label="Calibration demo progress"></progress><span id="cal-remaining">${running ? 'Preparing…' : success ? 'Complete · simulation' : '5 seconds to settle + 5 stable seconds'}</span></div><div class="cal-actions">${running ? button('Cancel calibration demo', 'cancel-calibration', 'button quiet', 'close') : button(success || failed ? 'Try again' : 'Start calibration demo', 'start-calibration', 'button primary', 'calibration')}${running ? button('Simulate a wobble', 'wobble', 'button quiet', 'reset') : button('Preview failure state', 'fail-calibration', 'button quiet')}</div><p class="demo-disclaimer">${icon('info')} This entire sequence is simulated. It does not access your gyro.</p></section>
  <div class="three-column cal-explain">${panel('1. Settle', '', '<p>Four lights count down to one across five seconds. A little time to take your hand away.</p>')}${panel('2. Measure', '', '<p>A fast chase means measurement is underway. A wobble extends the wait for a stable window, up to 30 seconds total.</p>')}${panel('3. Carry on', '', '<p>Your connected-idle lights return. On a failed HOME calibration, the previous bias is kept.</p>')}</div>
  ${panel('What recalibration can—and can’t—do', '', '<p>It measures the gyro’s stationary bias. It doesn’t move the cursor to the centre, replace angular velocity with accelerometer tilt, or establish an absolute heading.</p><p class="control-help">In the real app, HOME begins the same settling and measurement sequence. The countdown and measurement patterns are intentionally not customised in Lights.</p>', 'cal-technical')}`;
}

function profilesPage() {
  const custom = model.profiles.map(profile => ({ ...profile, icon: 'profiles', description: 'A feel you made yourself.', custom: true }));
  const canUpdate = model.profiles.some(profile => profile.name === model.activeProfile) && profileModified();
  return pageHead('PROFILES', 'Save your settings', 'Save a setup and switch between them.', `<div class="button-row">${canUpdate ? button('Save changes', 'update-profile', 'button quiet', 'check') : ''}${button('Save current as…', 'save-profile', 'button primary', 'profiles')}</div>`) +
  `<div class="profile-grid">${[...BUILTINS, ...custom].map(profile => `<section class="panel profile-card ${profile.name === model.activeProfile ? 'selected' : ''}"><div class="profile-art profile-${profile.icon}">${icon(profile.icon)}</div><span class="eyebrow">${profile.custom ? 'Your profile' : 'Built-in profile'}</span><h2>${escape(profile.name)}</h2><p>${escape(profile.description)}</p><div class="profile-facts"><span>${profile.custom ? profile.settings.pointer.sensitivity : preset(profile.name).pointer.sensitivity} px/°</span><span>${profile.name === 'Precision' ? 'Fine control' : profile.name === 'Presentation' ? 'Slide-ready' : 'Everyday ease'}</span></div><button type="button" data-profile="${escape(profile.name)}" class="button ${profile.name === model.activeProfile ? 'quiet' : 'primary'}">${profile.name === model.activeProfile ? icon('check') : ''}<span>${profile.name === model.activeProfile ? profileModified() ? 'Restore saved version' : 'Use again' : 'Use this profile'}</span></button>${profile.custom ? `<button type="button" class="text-link danger" data-delete-profile="${escape(profile.name)}">Delete profile</button>` : ''}${profile.name === model.activeProfile ? '<span class="current-profile">Current profile</span>' : ''}</section>`).join('')}</div>
  <section class="panel profile-portability"><div>${icon('download')}<span><h2>Your setup, to keep.</h2><p>Export and import design-preview settings. Files never leave your browser.</p></span></div><div class="button-row">${button('Import preview settings', 'import', 'button quiet')}${button('Export preview settings', 'export', 'button quiet', 'download')}</div></section><input type="file" id="settings-file" accept="application/json,.json" hidden><p class="section-footnote">Profiles and settings are shared between both design prototypes in this browser. Built-in profiles cannot be deleted; you can always restore them.</p>`;
}

function settingsPage() {
  return pageHead('SETTINGS', 'Preferences', 'Startup, recovery, appearance, and comfort.') +
  `<div class="two-column"><div class="panel-stack">${panel('Startup & recovery', 'Behaviour proposals for the finished application. These switches do not control systemd.', toggle('general.autoStart', 'Start with my desktop', 'Launch quietly when your GNOME session starts.') + toggle('general.recovery', 'Recover after reconnecting', 'Wait for the same remote and resume after a new calibration.') + toggle('general.calibrate', 'Calibrate each new connection', 'Start with a fresh stationary bias measurement.') + toggle('general.minimized', 'Keep the window out of the way', 'The background service can run without the settings window.') + `<div class="demo-service"><span><strong>Demo service</strong><small>${runtime.service ? 'Running in this preview only' : 'Stopped in this preview only'}</small></span>${button(runtime.service ? 'Stop demo' : 'Start demo', 'service', 'button quiet compact', runtime.service ? 'pause' : 'play')}</div>`)}
  ${panel('Appearance', '', selectControl('general.appearance', 'Appearance', ['System', 'Light', 'Dark'], 'Neo Wii follows this setting. Original Wii keeps its light palette.') + selectControl('general.motion', 'Interface motion', ['System', 'Reduced', 'Full'], 'Reduced motion keeps feedback and removes decorative movement.') + toggle('general.contrast', 'Stronger contrast', 'Clearer outlines and more defined surfaces.') + selectControl('general.textSize', 'Text size', [100, 110, 125]) + toggle('general.sound', 'Interface sounds', 'Quiet, original tones. Off by default; no Nintendo audio.'))}
  </div><div class="panel-stack">${panel('Messages', '', toggle('general.notifications', 'Connection & calibration messages', 'Status messages when they matter.'))}
  ${panel('Demo info', 'Simulated diagnostics, separated from real hardware.', `<dl class="diagnostics"><div><dt>Design target</dt><dd>Debian · GNOME Wayland</dd></div><div><dt>Input architecture</dt><dd>hid-wiimote → evdev → uinput</dd></div><div><dt>Device data</dt><dd>Simulated, not connected</dd></div><div><dt>Service state</dt><dd>${runtime.service ? 'Running' : 'Stopped'} · demo</dd></div><div><dt>IR sensor bar</dt><dd>Not required</dd></div></dl><div class="button-row">${button('View demo activity', 'activity', 'button quiet', 'info')}${button('Setup help', 'help', 'button quiet', 'help')}</div>`)}
  ${panel('Reset demo settings', '', '<p>Only this browser preview resets. Your real remote, service, saved pairing, and calibration stay untouched.</p>' + button('Reset preview settings', 'reset-all', 'button quiet danger', 'reset'))}
  <div class="privacy-note">${icon('check')}<p>Privacy.<span>No analytics, remote fonts, accounts, or background network requests. Preview settings live in this browser.</span></p></div></div></div>`;
}

function render(focus = '') {
  applyAppearance();
  const pages = { home, pointer: pointerPage, buttons: buttonPage, lights: lightPage, calibration: calibrationPage, profiles: profilesPage, settings: settingsPage };
  root.innerHTML = chrome(pages[runtime.page]());
  document.querySelector('#cal-phase')?.setAttribute('aria-live', 'polite');
  document.title = `WiiPointer · ${navigation.find(n => n[0] === runtime.page)[1]} · ${style === 'original' ? 'Original Wii' : 'Neo Wii'}`;
  bindPad(); updateFrames(performance.now());
  if (focus) document.getElementById(focus)?.focus({ preventScroll: true });
}
function updateControls() {
  document.querySelectorAll('[data-output]').forEach(output => { output.textContent = format(output.dataset.output); });
  document.querySelectorAll('input[type="range"]').forEach(input => {
    input.style.setProperty('--range-progress', `${100 * (Number(input.value) - Number(input.min)) / (Number(input.max) - Number(input.min))}%`);
    input.setAttribute('aria-valuetext', format(input.dataset.setting));
  });
  document.querySelectorAll('[data-feel]').forEach(control => {
    const pointer = preset(control.dataset.feel).pointer;
    control.classList.toggle('selected', pointer.sensitivity === model.settings.pointer.sensitivity && pointer.strength === model.settings.pointer.strength);
  });
  const points = curvePoints(model.settings.pointer);
  document.querySelector('[data-curve]')?.setAttribute('points', points);
  document.querySelector('[data-curve-fill]')?.setAttribute('points', `28,156 ${points} 328,156`);
  document.querySelectorAll('[data-profile-label]').forEach(node => { node.textContent = `${model.activeProfile}${profileModified() ? ' · Modified' : ''}`; });
}
function chooseButton(key) {
  if (!BUTTONS.includes(key)) return;
  runtime.selectedButton = key; runtime.learn = false; render();
  document.querySelector(`[data-mapping-row="${CSS.escape(key)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'instant' });
  document.querySelector(`[data-map="${CSS.escape(key)}"]`)?.focus({ preventScroll: true });
}
function sound() {
  if (!model.settings.general.sound) return;
  try {
    audio ||= new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === 'suspended') audio.resume();
    const oscillator = audio.createOscillator(); const volume = audio.createGain();
    oscillator.type = 'sine'; oscillator.frequency.setValueAtTime(760, audio.currentTime);
    oscillator.frequency.exponentialRampToValueAtTime(540, audio.currentTime + 0.045);
    volume.gain.setValueAtTime(0.025, audio.currentTime); volume.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.055);
    oscillator.connect(volume); volume.connect(audio.destination); oscillator.start(); oscillator.stop(audio.currentTime + 0.06);
  } catch { /* Audio is decorative; browser audio restrictions must not block controls. */ }
}
function openDialog(type, name = '') {
  const close = `<button type="button" class="button icon-button dialog-close" data-action="close-dialog" aria-label="Close dialog">${icon('close')}</button>`;
  let content;
  if (type === 'profile') content = `<p class="eyebrow">MAKE THIS FEEL YOURS</p><h2 id="dialog-title">A name for your setup.</h2><p>Your current settings will become a new profile in this browser.</p><form id="profile-form"><label for="profile-name">Profile name</label><input id="profile-name" name="name" maxlength="32" required placeholder="Sunday slides" autocomplete="off"><p id="profile-error" class="form-error" role="alert"></p><div class="button-row">${button('Cancel', 'close-dialog', 'button quiet')}<button class="button primary" type="submit">Save demo profile ${icon('check')}</button></div></form>`;
  if (type === 'reset') content = `<p class="eyebrow">JUST THE DEMO</p><h2 id="dialog-title">Start fresh?</h2><p>This resets settings and custom profiles for both prototypes in this browser. Your real Wii Remote and daemon are untouched.</p><div class="button-row">${button('Keep my settings', 'close-dialog', 'button quiet')}${button('Reset demo settings', 'confirm-reset', 'button primary danger')}</div>`;
  if (type === 'delete') content = `<h2 id="dialog-title">Delete “${escape(name)}”?</h2><p>This removes only the saved demo profile. Current pointer settings are kept.</p><div class="button-row">${button('Keep it', 'close-dialog', 'button quiet')}<button type="button" class="button primary danger" data-confirm-delete="${escape(name)}">Delete profile</button></div>`;
  if (type === 'activity') content = `<p class="eyebrow">DESIGN-PREVIEW EVENTS ONLY</p><h2 id="dialog-title">A little activity.</h2><ul class="activity-list">${runtime.events.length ? runtime.events.map(event => `<li><time>${event.time}</time><span>${escape(event.message)}</span></li>`).join('') : '<li>No demo events yet. Try a calibration or a profile.</li>'}</ul><p class="control-help">These are UI demo events, not your system journal or real sensor telemetry.</p>`;
  if (type === 'help') content = `<p class="eyebrow">About this preview</p><h2 id="dialog-title">Two designs, same controls.</h2><div class="help-steps"><p><span class="keycap">B</span><span><strong>Hold to aim.</strong> Release to stop.</span></p><p><span class="keycap">A</span><span><strong>Left click.</strong> The real remote’s A button clicks.</span></p><p><span class="keycap">HOME</span><span><strong>Calibration.</strong> Set down. Wait for five seconds.</span></p></div><p>Tab moves between controls. Arrow keys adjust sliders and navigate the Original Wii channel grid. Escape closes a dialog.</p><div class="inline-notice">All hardware states are simulated. No settings here change the real service. The preview remembers settings only in this browser.</div>${button('Got it', 'close-dialog', 'button primary')}`;
  dialog.innerHTML = close + content; dialog.setAttribute('aria-labelledby', 'dialog-title'); dialog.showModal();
  if (type === 'profile') dialog.querySelector('input').focus();
}
function exportSettings() {
  const blob = new Blob([JSON.stringify(model, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob); const a = document.createElement('a');
  a.href = url; a.download = 'wiipointer-design-preview.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  record('Exported preview settings.'); notify('Preview settings exported. Your real setup is unchanged.');
}
function startCalibration() {
  if (runtime.mode === 'disconnected' || runtime.mode === 'permission' || !runtime.service) {
    notify('Reconnect or start the demo service first. No real remote is required.'); return;
  }
  runtime.result = null; runtime.calibration = { start: performance.now(), stableSince: 5, wobbled: false };
  record('Started simulated calibration.'); runtime.page = 'calibration'; location.hash = '#calibration'; render();
}

document.addEventListener('click', event => {
  const target = event.target.closest('button, a, [data-map-key]');
  if (!target) return;
  if (target.tagName === 'A' && target.getAttribute('href')?.startsWith('#')) runtime.navigationOrigin = target.getBoundingClientRect();
  sound();
  if (target.dataset.mapKey) { chooseButton(target.dataset.mapKey); return; }
  if (target.dataset.feel) { model.settings.pointer = preset(target.dataset.feel).pointer; save(); render(); notify(`${({ Precision: 'Precise', Presentation: 'Balanced', Everyday: 'Quick' })[target.dataset.feel]} feel selected · demo only.`); return; }
  if (target.dataset.grip !== undefined) { runtime.grip = Number(target.dataset.grip); render(); return; }
  if (target.dataset.pattern) { model.settings.lights.pattern = target.dataset.pattern; save(); render(); return; }
  if (target.dataset.player) { model.settings.lights.player = Number(target.dataset.player); save(); render(); return; }
  if (target.dataset.light !== undefined) { model.settings.lights.mask[Number(target.dataset.light)] = !model.settings.lights.mask[Number(target.dataset.light)]; save(); render(); return; }
  if (target.dataset.profile) {
    model.activeProfile = target.dataset.profile;
    model.settings = structuredClone(model.profiles.find(p => p.name === model.activeProfile)?.settings || preset(model.activeProfile));
    save(); render(); record(`Selected ${model.activeProfile} profile.`); notify(`${model.activeProfile} is ready to try · demo only.`); return;
  }
  if (target.dataset.deleteProfile) { openDialog('delete', target.dataset.deleteProfile); return; }
  if (target.dataset.confirmDelete) {
    model.profiles = model.profiles.filter(p => p.name !== target.dataset.confirmDelete);
    if (model.activeProfile === target.dataset.confirmDelete) model.activeProfile = 'Presentation';
    save(); dialog.close(); render(); notify('Demo profile deleted. Current settings kept.'); return;
  }
  const action = target.dataset.action;
  if (!action) return;
  if (action === 'pause') { runtime.paused = !runtime.paused; render(); record(runtime.paused ? 'Paused the demo pointer.' : 'Resumed the demo pointer.'); }
  if (action === 'crt') { model.settings.general.crt = !model.settings.general.crt; save(); render(); }
  if (action === 'connect') { runtime.mode = 'ready'; render(); notify('Demo remote connected. Your real Bluetooth connection is untouched.'); }
  if (action === 'help' || action === 'activity') openDialog(action);
  if (action === 'close-dialog') dialog.close();
  if (action === 'save-profile') {
    if (model.profiles.length >= 8) notify('You have eight demo profiles. Delete one before adding another.');
    else openDialog('profile');
  }
  if (action === 'update-profile') {
    const profile = model.profiles.find(profile => profile.name === model.activeProfile);
    if (profile) { profile.settings = structuredClone(model.settings); save(); render(); notify('Changes saved to your demo profile.'); }
  }
  if (action === 'reset-all') openDialog('reset');
  if (action === 'confirm-reset') { runtime.calibration = null; runtime.result = null; model = freshModel(); save(); dialog.close(); render(); notify('Both design previews reset. Real settings unchanged.'); }
  if (action === 'reset-pointer') { model.settings.pointer = freshSettings().pointer; save(); render(); notify('Demo pointer settings restored.'); }
  if (action === 'reset-buttons') { model.settings.buttons = freshSettings().buttons; model.settings.shortcuts = freshSettings().shortcuts; save(); render(); notify('Demo button map restored.'); }
  if (action === 'learn') { runtime.learn = !runtime.learn; render(); notify('Select a button on the illustration. Physical input is not connected.'); }
  if (action === 'calibrate-page') location.hash = '#calibration';
  if (action === 'start-calibration') startCalibration();
  if (action === 'cancel-calibration') { runtime.calibration = null; runtime.result = null; render(); record('Cancelled simulated calibration; previous demo bias kept.'); notify('Calibration demo cancelled. Previous calibration kept.'); }
  if (action === 'wobble' && runtime.calibration) {
    runtime.calibration.stableSince = Math.max(5, (performance.now() - runtime.calibration.start) / 1000);
    runtime.calibration.wobbled = true; record('Simulated movement during calibration.'); notify('A wobble! Waiting for five steady seconds.');
  }
  if (action === 'fail-calibration') { runtime.calibration = null; runtime.result = 'failed'; render(); record('Previewed calibration failure; previous demo bias kept.'); }
  if (action === 'service') { runtime.service = !runtime.service; runtime.calibration = null; render(); record(`${runtime.service ? 'Started' : 'Stopped'} the simulated service.`); notify('Demo service changed. Your real systemd service is untouched.'); }
  if (action === 'export') exportSettings();
  if (action === 'import') document.querySelector('#settings-file').click();
  if (action === 'target') {
    if (runtime.paused || !runtime.service || ['disconnected', 'permission'].includes(runtime.mode)) return;
    runtime.hits++; document.querySelector('#hit-count').textContent = runtime.hits;
    target.style.left = `${22 + (runtime.hits * 29) % 57}%`; target.style.top = `${25 + (runtime.hits * 17) % 45}%`;
    target.animate?.([{ transform: 'translate(-50%,-50%) scale(.8)' }, { transform: 'translate(-50%,-50%) scale(1)' }], { duration: document.documentElement.dataset.motion === 'reduced' ? 0 : 180 });
  }
  if (action === 'centre-dot') bindPad();
});

document.addEventListener('input', event => {
  const input = event.target;
  if (input.dataset.shortcut) {
    model.settings.shortcuts[input.dataset.shortcut] = input.value;
    const mapped = document.querySelector('#mapped-action');
    if (mapped) mapped.textContent = mappedAction(runtime.selectedButton);
    save(); updateControls(); return;
  }
  if (!input.dataset.setting || input.type !== 'range') return;
  const [section, key] = input.dataset.setting.split('.');
  model.settings[section][key] = Number(input.value);
  if (key === 'sensitivity' && model.settings.pointer.linked) model.settings.pointer.vertical = Number(input.value);
  save(); updateControls();
});
document.addEventListener('change', async event => {
  const input = event.target;
  if (input.id === 'preview-state') {
    runtime.mode = input.value; runtime.calibration = null; runtime.result = null;
    record(`Previewed ${input.options[input.selectedIndex].text} state.`); render('preview-state'); return;
  }
  if (input.id === 'settings-file') {
    const file = input.files[0]; if (!file) return;
    try {
      if (file.size > 65536) throw new Error('Please choose a settings file smaller than 64 KB.');
      model = validateModel(JSON.parse(await file.text())); runtime.calibration = null; save(); render();
      notify('Preview settings imported. Real settings unchanged.'); record('Imported preview settings.');
    } catch (error) { notify(`Could not import: ${error.message}`); input.value = ''; }
    return;
  }
  if (input.dataset.map) { model.settings.buttons[input.dataset.map] = input.value; save(); render(input.id); return; }
  if (!input.dataset.setting || input.type === 'range') return;
  const [section, key] = input.dataset.setting.split('.');
  model.settings[section][key] = input.type === 'checkbox' ? input.checked : key === 'textSize' ? Number(input.value) : input.value;
  if (key === 'linked' && input.checked) model.settings.pointer.vertical = model.settings.pointer.sensitivity;
  save(); render(input.id);
});
document.addEventListener('submit', event => {
  if (event.target.id !== 'profile-form') return;
  event.preventDefault();
  const input = document.querySelector('#profile-name'); const name = input.value.trim();
  if (!name || [...BUILTINS, ...model.profiles].some(p => p.name.toLowerCase() === name.toLowerCase())) {
    document.querySelector('#profile-error').textContent = 'Choose a new name. Built-in names are reserved.'; input.focus(); return;
  }
  model.profiles.push({ name, settings: structuredClone(model.settings) }); model.activeProfile = name;
  save(); dialog.close(); render(); notify(`“${name}” saved in this browser.`); record('Saved a custom demo profile.');
});
document.addEventListener('keydown', event => {
  const mapped = event.target.closest('[data-map-key]');
  if (mapped && mapped.tagName.toLowerCase() === 'g' && ['Enter', ' '].includes(event.key)) {
    event.preventDefault(); chooseButton(mapped.dataset.mapKey);
  }
  const grid = event.target.closest('.channel-grid');
  if (!grid || !['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
  const items = [...grid.querySelectorAll('a')]; const index = items.indexOf(document.activeElement);
  const columns = getComputedStyle(grid).gridTemplateColumns.split(' ').length;
  const offset = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: columns, ArrowUp: -columns }[event.key];
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : Math.min(items.length - 1, Math.max(0, index + offset));
  event.preventDefault(); items[next]?.focus();
});
window.addEventListener('hashchange', () => {
  if (location.hash === '#main') return;
  runtime.page = navigation.some(n => n[0] === location.hash.slice(1)) ? location.hash.slice(1) : 'home';
  render(); document.querySelector('main h1')?.focus({ preventScroll: true }); window.scrollTo({ top: 0, behavior: 'instant' });
  if (document.documentElement.dataset.motion !== 'reduced') {
    const main = document.querySelector('main'); const rect = main.getBoundingClientRect(); const origin = runtime.navigationOrigin;
    if (origin) main.style.transformOrigin = `${Math.max(0, Math.min(rect.width, origin.x + origin.width / 2 - rect.x))}px ${Math.max(0, Math.min(rect.height, origin.y + origin.height / 2 - rect.y))}px`;
    main.animate(style === 'original'
      ? [{ opacity: .5, transform: 'scale(.985)' }, { opacity: 1, transform: 'scale(1)' }]
      : [{ opacity: .4, transform: 'translateY(6px)' }, { opacity: 1, transform: 'translateY(0)' }],
    { duration: 190, easing: 'cubic-bezier(.16,1,.3,1)' });
  }
});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyAppearance);
matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', applyAppearance);

function bindPad() {
  const pad = document.querySelector('#aim-pad'); const dot = document.querySelector('#aim-dot');
  if (!pad || !dot) return;
  let x = pad.clientWidth / 2, y = pad.clientHeight / 2, last = null, vx = 0, vy = 0;
  const move = () => { dot.style.transform = `translate3d(${x}px,${y}px,0)`; };
  move();
  pad.onpointerleave = () => { last = null; vx = vy = 0; };
  pad.onpointermove = event => {
    if (runtime.paused || !runtime.service || ['disconnected', 'permission'].includes(runtime.mode)) return;
    const now = performance.now();
    if (!last) { last = { x: event.clientX, y: event.clientY, now }; return; }
    const p = model.settings.pointer; const dt = Math.max(1 / 240, Math.min(.05, (now - last.now) / 1000));
    let dx = event.clientX - last.x, dy = event.clientY - last.y;
    if (!p.roll) { const angle = runtime.grip * Math.PI / 180; [dx, dy] = [dx * Math.cos(angle) - dy * Math.sin(angle), dx * Math.sin(angle) + dy * Math.cos(angle)]; }
    const alpha = p.smoothing === 0 ? 1 : -Math.expm1(-dt / (p.smoothing / 1000));
    vx += alpha * (dx / dt - vx); vy += alpha * (dy / dt - vy);
    const speed = Math.hypot(vx, vy) / 12; const response = gain(speed, p);
    const quiet = speed < p.deadzone;
    x = Math.max(14, Math.min(pad.clientWidth - 14, x + (quiet ? 0 : vx * dt * response * p.sensitivity / 12 * (p.invertX ? 1 : -1))));
    y = Math.max(14, Math.min(pad.clientHeight - 14, y + (quiet ? 0 : vy * dt * response * p.vertical / 12 * (p.invertY ? -1 : 1))));
    move(); document.querySelector('#gain-value').textContent = `${response.toFixed(2)}×`;
    last = { x: event.clientX, y: event.clientY, now };
  };
}

function updateFrames(now) {
  const minute = Math.floor(Date.now() / 60000);
  if (style === 'original' && minute !== runtime.clockMinute) {
    runtime.clockMinute = minute;
    const clock = clockText(); const time = document.querySelector('[data-clock-time]');
    if (time) { time.textContent = clock.time; time.dateTime = clock.iso; document.querySelector('[data-clock-date]').textContent = clock.date; }
  }
  let frame;
  if (runtime.calibration) {
    const elapsed = (now - runtime.calibration.start) / 1000;
    frame = calibrationFrame(elapsed, runtime.calibration.stableSince);
    if (['complete', 'failed'].includes(frame.phase)) {
      runtime.result = frame.phase; runtime.calibration = null;
      if (frame.phase === 'complete') { model.lastCalibration = Date.now(); save(); }
      record(frame.phase === 'complete' ? 'Simulated calibration accepted.' : 'Simulated calibration timed out; previous bias kept.');
      render(); notify(frame.phase === 'complete' ? 'All steady. Demo calibration complete; real gyro untouched.' : 'No stable window. Previous demo calibration kept.');
      return;
    }
    const title = document.querySelector('#cal-title');
    if (title) {
      const copy = {
        'cal-title': frame.phase === 'settling' ? 'Let it settle.' : 'Finding your steady.',
        'cal-phase': frame.phase === 'settling' ? 'HANDS OFF IN A MOMENT' : 'MEASURING · SIMULATION',
        'cal-description': frame.phase === 'settling' ? 'Set it on a stable surface. A little time to take your hand away.' : runtime.calibration.wobbled ? 'A wobble was detected. Waiting for five steady seconds; your previous bias is safe.' : 'Five stable seconds. The fast chase means measurement is underway.',
        'cal-remaining': `${frame.remaining} ${frame.remaining === 1 ? 'second' : 'seconds'} ${frame.phase === 'settling' ? 'to settle' : 'of stillness to go'}`,
      };
      for (const [id, value] of Object.entries(copy)) {
        const node = document.getElementById(id);
        if (node.textContent !== value) node.textContent = value;
      }
      document.querySelector('#cal-progress').value = frame.progress;
    }
  }
  const reduced = document.documentElement.dataset.motion === 'reduced';
  const idle = runtime.mode === 'disconnected' ? [false, false, false, false] : idleLights(model.settings, now / 1000, model.activeProfile === 'Presentation', reduced);
  document.querySelectorAll('[data-led-context]').forEach(group => {
    const on = group.dataset.ledContext === 'calibration' && frame ? reduced && frame.phase === 'measuring' ? [true, true, true, true] : frame.lights : idle;
    group.querySelectorAll('[data-led]').forEach(light => light.classList.toggle('is-on', on[Number(light.dataset.led)]));
  });
}
let previousFrame = 0;
function animate(now) { if (now - previousFrame > 65) { previousFrame = now; updateFrames(now); } requestAnimationFrame(animate); }
runtime.page = navigation.some(n => n[0] === location.hash.slice(1)) ? location.hash.slice(1) : 'home';
render(); requestAnimationFrame(animate);
if (loadNotice) notify(loadNotice);
