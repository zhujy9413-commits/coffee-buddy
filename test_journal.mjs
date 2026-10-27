import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('./web/journal.js',import.meta.url),'utf8');
const {tastingDraft,photoMenuDraft,reactionLabels,feedbackLines,shopLinkHint}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

test('explicit average and legacy undecided have distinct labels, including actual taste',()=>{
  assert.equal(reactionLabels.okay,'一般');
  assert.equal(reactionLabels.neutral,'还说不准');
  assert.deepEqual(feedbackLines({reaction:'okay',observed_on:'2026-01-01',tasted_flavors:['微焦','微苦']}),['上次评价：一般 · 2026-01-01','实际喝到：微焦、微苦']);
  assert.deepEqual(feedbackLines({reaction:'neutral',observed_on:'2026-01-01',tasted_flavors:[]}),['上次评价：还说不准 · 2026-01-01']);
  assert.deepEqual(feedbackLines(null),[]);
});

test('only missing branch information prompts for linking, without requiring device coordinates',()=>{
  assert.match(shopLinkHint({}),/尚未填写店铺/);
  assert.match(shopLinkHint({cafe:'测试店'}),/地址或地图关联/);
  assert.equal(shopLinkHint({cafe:'测试店',address:'测试地址'}),'');
  assert.equal(shopLinkHint({cafe:'测试店',provider_id:'test-poi'}),'');
});

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

test('applying a photo while editing an old tasting starts a separate menu with no old feedback',()=>{
  const context={id:'old-id',kind:'tasting',product:'旧饮品',bean:'旧豆子',reaction:'like',
    tasted_flavors:['旧感受'],note:'旧备注',cafe:'用户选择的店',address:'用户确认地址',
    provider_id:'user-branch',brew:'冰美式',source_note:'用户来源',observed_on:'2020-01-01'};
  const item={product:'图片中的新产品',label_flavors:['花香'],brew:'手冲',roast:'浅烘',
    id:'model-id',cafe:'模型猜测店',reaction:'like',tasted_flavors:['模型伪造亲历']};
  const draft=photoMenuDraft(item,context,'2026-10-25');
  assert.equal(draft.id,'');assert.equal(draft.kind,'menu');assert.equal(draft.product,'图片中的新产品');
  assert.equal(draft.observed_on,'2026-10-25');assert.equal(draft.reaction,'neutral');
  assert.deepEqual(draft.tasted_flavors,[]);assert.equal(draft.note,'');assert.equal(draft.bean,'');
  for(const field of ['cafe','address','provider_id','source_note'])assert.equal(draft[field],context[field]);
  assert.equal(draft.brew,'手冲');assert.equal(context.id,'old-id');assert.equal(context.reaction,'like');
});

test('photo unknowns stay empty and only an existing form choice can supply the default brew',()=>{
  const draft=photoMenuDraft({product:'图片产品',roast:'猜测烘焙'}, {}, '2026-10-25');
  assert.equal(draft.roast,'未知');assert.equal(draft.brew,'');assert.equal(draft.cafe,'');
  assert.equal(draft.location,null);assert.deepEqual(draft.label_flavors,[]);
  assert.equal(photoMenuDraft({product:'图片产品'},{brew:'冷萃'},'2026-10-25').brew,'冷萃');
});
