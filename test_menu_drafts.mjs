import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('./web/menu-drafts.js',import.meta.url),'utf8');
const {parseMenuText,draftsFromItems}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
let serial=0;const makeId=()=>`test-${++serial}`;

test('structured lines preserve blanks and user-supplied flavors without inventing bean details',()=>{
  const rows=parseMenuText('苹果特调\n测试手冲 | 测试豆 | 浅烘 | 柑橘、茉莉','',makeId);
  assert.equal(rows.length,2);assert.equal(rows[0].brew,'');assert.equal(rows[0].bean,'');assert.equal(rows[0].roast,'未知');
  assert.equal(rows[1].label_flavors,'柑橘、茉莉');assert.equal(rows[1].roast,'浅烘');assert.notEqual(rows[0].id,rows[1].id);
});
test('tab-separated cells retain empty bean and roast columns',()=>{
  const row=parseMenuText('测试 A\t\t\t柑橘','手冲',makeId)[0];
  assert.equal(row.bean,'');assert.equal(row.roast,'未知');assert.equal(row.brew,'手冲');assert.equal(row.label_flavors,'柑橘');
});
test('invalid roast or extra columns are surfaced rather than silently discarded',()=>{
  for(const raw of ['','产品 | 豆子 | 不确定烘焙','产品 | 豆子 | 浅烘 | 花香 | 多余资料',Array(21).fill('A').join('\n')])
    assert.throws(()=>parseMenuText(raw,'',makeId));
});
test('photo output only supplies product facts and receives fresh IDs',()=>{
  const row=draftsFromItems([{id:'untrusted',product:'测试豆',kind:'tasting',reaction:'like',cafe:'模型猜测店名',label_flavors:['柑橘']}],makeId)[0];
  assert.notEqual(row.id,'untrusted');assert.equal(row.product,'测试豆');assert.equal(row.roast,'未知');
  for(const key of ['kind','reaction','cafe','owner'])assert.equal(row[key],undefined);
});
