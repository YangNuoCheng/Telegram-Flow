const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'web', 'index.html'), 'utf8');
const code = source.slice(source.indexOf('let hold = null;'), source.indexOf('feedEl.addEventListener("touchstart"'));
const events = {}, windowEvents = {}, documentEvents = {};
let timer, cancelled = 0, removed = 0;
const card = { dataset: { key: 'video' }, append() {} };
const video = { playbackRate: 1.25, closest: () => card };
const context = {
  active: card, lastTap: {}, touch: { moved: false },
  feedEl: { addEventListener: (event, callback) => events[event] = callback },
  window: { addEventListener: (event, callback) => windowEvents[event] = callback },
  document: { hidden: false, addEventListener: (event, callback) => documentEvents[event] = callback,
    createElement: () => ({ remove: () => removed++ }) },
  setTimeout: (callback, delay) => { assert.equal(delay, 400); timer = callback; return 1; },
  clearTimeout: () => cancelled++, Math,
};
vm.createContext(context); vm.runInContext(code, context);
const down = () => events.pointerdown({ button: 0, isPrimary: true, clientX: 20, clientY: 20, target: { closest: () => video } });
down(); assert.equal(video.playbackRate, 1.25); timer(); assert.equal(video.playbackRate, 2);
assert(context.touch.moved); assert.equal(context.lastTap, null);
windowEvents.pointerup(); assert.equal(video.playbackRate, 1.25); assert.equal(removed, 1);
down(); events.pointermove({ clientX: 50, clientY: 20 }); assert.equal(video.playbackRate, 1.25);
down(); timer(); windowEvents.pointercancel(); assert.equal(video.playbackRate, 1.25);
down(); timer(); context.document.hidden = true; documentEvents.visibilitychange(); assert.equal(video.playbackRate, 1.25);
assert(cancelled >= 4);
console.log('PASS: hold doubles speed; release, movement, cancellation and background restore speed');
