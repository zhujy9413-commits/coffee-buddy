import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('./web/location.js', import.meta.url), 'utf8');
const {getLocation} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
test('does not request location until explicitly called, then returns WGS84 without continuous tracking', async()=>{
  let calls=0;
  const env={isSecureContext:true,navigator:{geolocation:{getCurrentPosition(success,error,options){calls++;assert.equal(options.timeout,20000);assert.equal(options.enableHighAccuracy,false);success({coords:{latitude:39.9,longitude:116.4,accuracy:50}});}}}};
  assert.equal(calls,0);
  assert.deepEqual(await getLocation(env),{lat:39.9,lng:116.4,system:'wgs84',accuracy:50});
  assert.equal(calls,1);
});
test('permission denial, unavailability and timeout all offer manual location',async()=>{
  for (const code of [1,2,3]) {
    const env={isSecureContext:true,navigator:{geolocation:{getCurrentPosition(success,error){error({code});}}}};
    await assert.rejects(getLocation(env),/手动/);
  }
});
test('insecure origin and unsupported browsers do not request location',async()=>{
  await assert.rejects(getLocation({isSecureContext:false}),/HTTPS/);
  await assert.rejects(getLocation({isSecureContext:true,navigator:{}}),/手动/);
});
