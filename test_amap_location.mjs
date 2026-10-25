import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('./web/amap-location.js',import.meta.url),'utf8');
const {parseAmapPosition,getAmapLocation,describeAmapFailure}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const point=(type='ip',accuracy)=>({position:{getLat:()=>39.9,getLng:()=>116.4},location_type:type,accuracy,formattedAddress:'公共测试地标'});
const sdkEnv=(result,status='complete')=>({isSecureContext:true,setTimeout,clearTimeout,AMap:{Geolocation:class {
  constructor(options){assert.equal(options.getCityWhenFail,false);assert.equal(options.convert,true);}
  getCurrentPosition(callback){callback(status,result);}
}}});

test('network and unknown-precision results require confirmation; precise h5 uses GCJ02',()=>{
  assert.equal(parseAmapPosition(point()).approximate,true);
  assert.equal(parseAmapPosition(point('h5')).approximate,true);
  assert.equal(parseAmapPosition(point('h5',800)).approximate,true);
  const exact=parseAmapPosition(point('h5',25));
  assert.equal(exact.approximate,false);
  assert.equal(exact.system,'gcj02');
});
test('city-only or malformed points cannot be used as a current position',()=>{
  for(const result of [point('ipcity'),{}, {position:{lat:null,lng:null}}, {position:{lat:'',lng:false}}, {position:{lat:95,lng:116}}]) {
    assert.throws(()=>parseAmapPosition(result),/手动/);
  }
});
test('one fusion request returns usable position or a manual fallback error',async()=>{
  const result=await getAmapLocation({key:'test-public-key'},sdkEnv(point()));
  assert.equal(result.type,'ip');
  await assert.rejects(getAmapLocation({key:'test'},sdkEnv({},'error')),/手动/);
  await assert.rejects(getAmapLocation({},sdkEnv(point())),/配置/);
  await assert.rejects(getAmapLocation({key:'test'},{isSecureContext:false}),/HTTPS/);
});
test('missing callbacks are bounded and late success cannot change a timed-out request',async()=>{
  let expire,callback;
  const env={isSecureContext:true,setTimeout:fn=>{expire=fn;return 1;},clearTimeout:()=>{},AMap:{Geolocation:class {
    getCurrentPosition(fn){callback=fn;}
  }}};
  const pending=getAmapLocation({key:'test'},env);
  await Promise.resolve();
  expire();
  await assert.rejects(pending,/手动/);
  callback('complete',point());
});
test('SDK loads only when called, uses public key and same-origin security proxy',async()=>{
  let appends=0;
  const env={isSecureContext:true,setTimeout,clearTimeout,location:{origin:'http://127.0.0.1:8765'},
    document:{createElement:()=>({remove(){}}),head:{append(script){
      appends++;
      assert.match(script.src,/^https:\/\/webapi\.amap\.com\/maps\?/);
      assert.doesNotMatch(script.src,/jscode|securityJsCode/);
      env.AMap={...sdkEnv(point()).AMap,plugin:(_,done)=>done()};
      env.__coffeeAmapReady();
    }}}};
  assert.equal(appends,0);
  await getAmapLocation({key:'test-public'},env);
  assert.equal(appends,1);
  assert.deepEqual(env._AMapSecurityConfig,{serviceHost:'http://127.0.0.1:8765/_AMapService'});
});

test('a failed fusion result distinguishes both IP and browser failure stages',async()=>{
  const failure={info:'FAILED',message:'Get ipLocation failed.Get geolocation time out.'};
  await assert.rejects(getAmapLocation({key:'test'},sdkEnv(failure,'error')),error=>{
    assert.equal(error.code,'IP_LOCATION_FAILED / BROWSER_TIMEOUT');
    assert.match(error.message,/网络 IP/);
    assert.match(error.message,/浏览器定位超时/);
    return true;
  });
  assert.equal(describeAmapFailure({message:'Geolocation permission denied.'}).code,'BROWSER_PERMISSION_DENIED');
  assert.equal(describeAmapFailure({message:'Browser not Support html5 geolocation.'}).code,'BROWSER_UNSUPPORTED');
  assert.equal(describeAmapFailure({message:'Get geolocation failed.'}).code,'BROWSER_POSITION_UNAVAILABLE');
});

test('service configuration errors stay distinct from browser permissions and usage limits',()=>{
  for(const result of [{info:'USERKEY_PLAT_NOMATCH'}, {infocode:'10009'}]) {
    const failure=describeAmapFailure(result);
    assert.equal(failure.code,'USERKEY_PLAT_NOMATCH');
    assert.match(failure.message,/平台不匹配/);
    assert.doesNotMatch(failure.message,/定位权限/);
  }
  assert.equal(describeAmapFailure({info:'INVALID_USER_SCODE'}).code,'INVALID_USER_SCODE');
  assert.equal(describeAmapFailure({infocode:10003}).code,'DAILY_QUERY_OVER_LIMIT');
  assert.match(describeAmapFailure({info:'ACCESS_TOO_FREQUENT'}).message,/稍后/);
});

test('unrecognized provider text, secrets, coordinates and URLs are never echoed',()=>{
  const sensitive='https://provider.example/?key=private-key&jscode=private-code&location=116.123456,39.123456 <script>alert(1)</script>';
  for(const info of ['FAILED','INVALID_USER_KEY',sensitive]) {
    const failure=describeAmapFailure({info,message:sensitive,infocode:'987654'});
    assert.doesNotMatch(failure.message,/private-key|private-code|116\.123456|39\.123456|provider\.example|script|987654/);
    assert.match(failure.message,/诊断代码/);
  }
  assert.equal(describeAmapFailure({info:'xINVALID_USER_KEYx'}).code,'AMAP_POSITION_FAILED');
  assert.equal(describeAmapFailure(null).code,'AMAP_POSITION_FAILED');
  assert.equal(describeAmapFailure({info:{secret:sensitive},message:[sensitive]}).code,'AMAP_POSITION_FAILED');
});
