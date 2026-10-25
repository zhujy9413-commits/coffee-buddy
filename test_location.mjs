import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
let source = await readFile(new URL('./web/location.js', import.meta.url), 'utf8');
const amap = await readFile(new URL('./web/amap-location.js', import.meta.url), 'utf8');
source = source.replace("'./amap-location.js'", JSON.stringify('data:text/javascript;base64,' + Buffer.from(amap).toString('base64')));
const {getLocation,getCurrentLocation,prefersDeviceLocation} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const clock = {setTimeout,clearTimeout};
test('does not request location until explicitly called, then returns WGS84 without continuous tracking', async()=>{
  let calls=0;
  const env={...clock,isSecureContext:true,navigator:{geolocation:{getCurrentPosition(success,error,options){calls++;assert.equal(options.timeout,20000);assert.equal(options.enableHighAccuracy,false);success({coords:{latitude:39.9,longitude:116.4,accuracy:50}});}}}};
  assert.equal(calls,0);
  assert.deepEqual(await getLocation(env),{lat:39.9,lng:116.4,system:'wgs84',accuracy:50,approximate:false});
  assert.equal(calls,1);
});
test('permission denial, unavailability and timeout all offer manual location',async()=>{
  for (const code of [1,2,3]) {
    const env={...clock,isSecureContext:true,navigator:{geolocation:{getCurrentPosition(success,error){error({code});}}}};
    await assert.rejects(getLocation(env),/手动/);
  }
});
test('insecure origin and unsupported browsers do not request location',async()=>{
  await assert.rejects(getLocation({isSecureContext:false}),/HTTPS/);
  await assert.rejects(getLocation({isSecureContext:true,navigator:{}}),/手动/);
});

test('iPhone, Android and iPad desktop mode request device location without loading the SDK',async()=>{
  for (const device of [{userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)'},
                        {userAgent:'Mozilla/5.0 (Linux; Android 15)'},
                        {userAgent:'Mozilla/5.0 (Macintosh)',platform:'MacIntel',maxTouchPoints:5}]) {
    let calls=0;
    const env={...clock,isSecureContext:true,navigator:{...device,geolocation:{getCurrentPosition(success,error,options){
      calls++; assert.equal(options.enableHighAccuracy,true);
      success({coords:{latitude:39.9,longitude:116.4,accuracy:20}});
    }}},document:{createElement(){throw new Error('SDK must not load on device path');}}};
    assert.equal(prefersDeviceLocation({provider:'amap'},env),true);
    const pending=getCurrentLocation({provider:'amap',key:'test'},env);
    assert.equal(calls,1,'device request starts in the click call, without awaiting an SDK');
    assert.equal((await pending).system,'wgs84');
  }
});

test('denying mobile device location does not start an IP fallback',async()=>{
  const env={...clock,isSecureContext:true,navigator:{userAgent:'iPhone',geolocation:{getCurrentPosition(success,error){error({code:1});}}},
    document:{createElement(){throw new Error('Unexpected third-party request');}}};
  await assert.rejects(getCurrentLocation({provider:'amap',key:'test'},env),e=>e.code==='BROWSER_PERMISSION_DENIED');
});

test('desktop keeps the configured fusion provider without requesting native location twice',async()=>{
  const env={...clock,isSecureContext:true,navigator:{userAgent:'Mozilla/5.0 (Macintosh)',maxTouchPoints:0,
    geolocation:{getCurrentPosition(){throw new Error('Unexpected native request');}}},AMap:{Geolocation:class {
      getCurrentPosition(callback){callback('complete',{position:{lat:39.9,lng:116.4},location_type:'ip'});}
    }}};
  assert.equal(prefersDeviceLocation({provider:'amap'},env),false);
  assert.equal((await getCurrentLocation({provider:'amap',key:'test'},env)).system,'gcj02');
});

test('missing native callbacks are bounded and late success cannot finish a failed request',async()=>{
  let expire,late;
  const env={isSecureContext:true,setTimeout(fn,delay){assert.equal(delay,22000);expire=fn;return 1;},clearTimeout(){},
    navigator:{geolocation:{getCurrentPosition(success){late=success;}}}};
  const pending=getLocation(env);
  expire();
  await assert.rejects(pending,e=>e.code==='BROWSER_CALLBACK_TIMEOUT');
  late({coords:{latitude:39.9,longitude:116.4,accuracy:20}});
});

test('unknown device accuracy requires confirmation and invalid coordinates are rejected',async()=>{
  const env=coords=>({...clock,isSecureContext:true,navigator:{geolocation:{getCurrentPosition(success){success({coords});}}}});
  assert.equal((await getLocation(env({latitude:39.9,longitude:116.4}))).approximate,true);
  await assert.rejects(getLocation(env({latitude:undefined,longitude:116.4})),e=>e.code==='INVALID_POSITION');
});
