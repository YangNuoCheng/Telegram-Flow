const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'index.html'), 'utf8');
const fillSource = source.slice(source.indexOf('async function fill() {'), source.indexOf('async function prepare(c)'));
let displayed = 0, retries = 0;
const context = {
  state: { gen: 1, retryUntil: 0, done: true }, raw: [{ key: 'pending' }], preparing: 0,
  BUFFER: 200, AHEAD: 0, PREP: 1, insertion: Promise.resolve(), Date, mayShow: () => true, ahead: () => displayed,
  retryFill: () => retries++, feedEl: { insertBefore: () => displayed++ },
  near: { observe() {} }, seen: { observe() {} }, $: () => null,
  load: async () => { throw Error('Unexpected fetch during cooldown'); },
  prepare: async () => { context.state.retryUntil = Date.now() + 30000; throw { retry: true }; },
};
vm.createContext(context);
vm.runInContext(fillSource, context);
(async () => {
  await context.fill(); await new Promise(setImmediate);
  assert.equal(context.raw.length, 1);
  assert.equal(context.preparing, 0);
  assert.equal(displayed, 0);
  assert(retries > 0);
  context.state.retryUntil = 0;
  context.prepare = async () => ({ dataset: { key: 'pending' } });
  await context.fill(); await new Promise(setImmediate);
  assert.equal(context.raw.length, 0);
  assert.equal(displayed, 1);
  assert.equal(context.preparing, 0);
  console.log('PASS: pending card survives cooldown and queue resumes');
  displayed = 0;
  context.AHEAD = 1; context.PREP = 2; context.insertion = Promise.resolve();
  context.raw = [{ key: 'slow-video' }, { key: 'fast-photo' }];
  let finishVideo;
  const order = [];
  context.feedEl.insertBefore = el => { order.push(el.dataset.key); displayed++; };
  context.prepare = c => c.key === 'slow-video'
    ? new Promise(resolve => { finishVideo = () => resolve({ dataset: { key: c.key } }); })
    : Promise.resolve({ dataset: { key: c.key } });
  await context.fill(); await new Promise(setImmediate);
  assert.equal(displayed, 0);
  finishVideo(); await new Promise(setImmediate);
  assert.deepEqual(order, ['slow-video', 'fast-photo']);
  console.log('PASS: faster photo preparation cannot overtake the preceding video');
})().catch(error => { console.error(error); process.exitCode = 1; });
