import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('./web/journal.js',import.meta.url),'utf8');
const {tastingDraft}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

test('menu becomes a separate tasting without carrying a prior judgment or date',()=>{
  const old={id:'old-entry',kind:'menu',product:'豆单 A',bean:'豆 A',batch:'批次 1',brew:'手冲',brew_category:'black',
    label_flavors:['柑橘'],tasted_flavors:['苦'],reaction:'like',note:'旧感受',observed_on:'2020-01-01',
    source_note:'店内豆单',provider_id:'branch-a',location:{lat:39.9,lng:116.4,system:'gcj02'}};
  const draft=tastingDraft(old,'2026-10-25');
  assert.equal(draft.id,'');assert.equal(draft.kind,'tasting');assert.equal(draft.observed_on,'2026-10-25');
  assert.equal(draft.reaction,'neutral');assert.equal(draft.note,'');assert.deepEqual(draft.tasted_flavors,[]);
  for(const field of ['product','bean','batch','brew','brew_category','source_note','provider_id'])assert.equal(draft[field],old[field]);
  draft.label_flavors.push('new');draft.location.lat=0;
  assert.deepEqual(old.label_flavors,['柑橘']);assert.equal(old.location.lat,39.9);
});

test('unknown bean information stays blank rather than being inferred',()=>{
  const draft=tastingDraft({product:'冰美式'},'2026-10-25');
  assert.equal(draft.bean,'');assert.equal(draft.batch,'');assert.equal(draft.provider_id,'');
  assert.equal(draft.location,null);assert.deepEqual(draft.label_flavors,[]);
});
