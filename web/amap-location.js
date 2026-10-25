// Loaded locally at page start; the third-party SDK is requested only on a click.
let sdkPromise;

function locationError(code, message) {
  const error = new Error(message + ' 可手动选择地点继续查店。诊断代码：' + code + '。');
  error.code = code;
  return error;
}

// Only report recognized provider codes and fixed explanations. Raw SDK errors
// may contain request URLs, identifiers or coordinates and must never be echoed.
const serviceErrors = {
  INVALID_USER_KEY: '高德 Key 无效或已过期，需要检查配置。',
  INVALID_USER_SCODE: '高德安全码校验未通过，需要检查它与 JS API Key 是否配套。',
  INVALID_USER_DOMAIN: '当前网页地址未通过高德的域名校验，需要检查域名配置。',
  INVALID_USER_IP: '高德的 IP 白名单校验未通过，需要检查服务端配置。',
  INVALID_USER_SIGNATURE: '高德请求签名校验未通过，需要检查服务端配置。',
  USERKEY_PLAT_NOMATCH: '高德返回 Key 平台不匹配，需要检查 Key 类型及调用方式。',
  SERVICE_NOT_AVAILABLE: '高德接口不可用，需要检查服务权限和接口配置。',
  DAILY_QUERY_OVER_LIMIT: '高德返回当日调用额度已用完，请检查控制台用量。',
  ACCESS_TOO_FREQUENT: '高德返回请求过于频繁，请稍后再试。',
  IP_QUERY_OVER_LIMIT: '高德返回当前网络 IP 的调用次数超限，请稍后再试。',
};
const serviceCodeNames = {'10001':'INVALID_USER_KEY','10002':'SERVICE_NOT_AVAILABLE',
  '10003':'DAILY_QUERY_OVER_LIMIT','10004':'ACCESS_TOO_FREQUENT','10005':'INVALID_USER_IP',
  '10006':'INVALID_USER_DOMAIN','10007':'INVALID_USER_SIGNATURE','10008':'INVALID_USER_SCODE',
  '10009':'USERKEY_PLAT_NOMATCH','10010':'IP_QUERY_OVER_LIMIT'};

export function describeAmapFailure(result) {
  const fields = ['info', 'message', 'infocode', 'code'].map(key => {
    const value = result?.[key];
    return typeof value === 'string' ? value.slice(0, 4000) : typeof value === 'number' ? String(value) : '';
  });
  const codes = Object.keys(serviceErrors).filter(code => fields.some(value =>
    new RegExp('(^|[^A-Za-z0-9_])' + code + '($|[^A-Za-z0-9_])').test(value)));
  const numericCode = String(result?.infocode ?? '');
  if (serviceCodeNames[numericCode] && !codes.includes(serviceCodeNames[numericCode])) codes.push(serviceCodeNames[numericCode]);
  if (codes.length) return locationError(codes.join(' / '), codes.map(code => serviceErrors[code]).join(' '));

  const message = fields.join(' ').toLowerCase();
  const reasons = [];
  const add = (code, text) => reasons.push({code, text});
  if (/get\s+ip\s*location\s+failed/.test(message)) add('IP_LOCATION_FAILED', '网络 IP 定位未能取得位置。');
  if (/geolocation\s+permission\s+denied|\bpermission_denied\b/.test(message)) add('BROWSER_PERMISSION_DENIED', '浏览器未允许本次定位，请检查系统与网站定位权限。');
  if (/get\s+geolocation\s+time\s*out|\btime_?out\b/.test(message)) add('BROWSER_TIMEOUT', '浏览器定位超时，暂未取得设备位置。');
  if (/browser\s+not\s+support\s+html5\s+geolocation/.test(message)) add('BROWSER_UNSUPPORTED', '当前浏览器不支持设备定位。');
  if (/get\s+geolocation\s+failed|\bposition_unavailable\b/.test(message)) add('BROWSER_POSITION_UNAVAILABLE', '浏览器的位置服务未返回可用位置。');
  if (reasons.length) return locationError(reasons.map(r => r.code).join(' / '), reasons.map(r => r.text).join(' '));
  return locationError('AMAP_POSITION_FAILED', '高德未能取得位置，未返回可识别的具体原因。');
}

export function parseAmapPosition(result) {
  if (!result || result.location_type === 'ipcity') throw locationError('CITY_ONLY', '目前只能定位到城市，无法判断你附近的店铺。');
  const rawLat=result.position?.getLat?.() ?? result.position?.lat;
  const rawLng=result.position?.getLng?.() ?? result.position?.lng;
  const validNumber=v=>typeof v==='number'||(typeof v==='string'&&v.trim()!=='');
  const lat = validNumber(rawLat)?Number(rawLat):NaN;
  const lng = validNumber(rawLng)?Number(rawLng):NaN;
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat)>90 || Math.abs(lng)>180) throw locationError('INVALID_POSITION', '高德返回的位置格式无效。');
  const type = String(result.location_type || '').toLowerCase();
  const accuracy = Number.isFinite(result.accuracy) && result.accuracy>0 ? result.accuracy : null;
  const label = typeof result.formattedAddress === 'string' ? result.formattedAddress.slice(0,200) : '';
  return {lat,lng,system:'gcj02',accuracy,provider:'amap',type,label,
    approximate: !['h5','sdk'].includes(type) || accuracy===null || accuracy>500};
}

function loadSdk(config, env) {
  if (env.AMap?.Geolocation) return Promise.resolve(env.AMap);
  if (sdkPromise) return sdkPromise;
  sdkPromise = new Promise((resolve,reject)=>{
    const script=env.document.createElement('script');
    let settled=false;
    const finish=(error)=>{
      if(settled)return;settled=true;
      env.clearTimeout(timer);
      env.__coffeeAmapReady=()=>{};
      if(error){script.remove();reject(error);} else resolve(env.AMap);
    };
    const timer=env.setTimeout(()=>finish(locationError('SDK_LOAD_TIMEOUT', '高德定位组件加载超时，请检查网络。')),15000);
    env._AMapSecurityConfig={serviceHost:env.location.origin+'/_AMapService'};
    env.__coffeeAmapReady=()=>{
      try {env.AMap.plugin('AMap.Geolocation',()=>finish(env.AMap?.Geolocation ? null : locationError('SDK_PLUGIN_UNAVAILABLE', '高德定位插件未能就绪。')));}
      catch {finish(locationError('SDK_PLUGIN_FAILED', '高德定位插件加载失败。'));}
    };
    script.async=true;
    script.src='https://webapi.amap.com/maps?v=2.0&key='+encodeURIComponent(config.key)+'&callback=__coffeeAmapReady';
    script.onerror=()=>finish(locationError('SDK_LOAD_FAILED', '无法加载高德定位组件，请检查网络或页面脚本限制。'));
    env.document.head.append(script);
  });
  sdkPromise.catch(()=>{sdkPromise=undefined;});
  return sdkPromise;
}

export async function getAmapLocation(config, env=globalThis) {
  if(!env.isSecureContext) throw locationError('INSECURE_CONTEXT', '当前网页不是安全访问环境，定位需要 HTTPS 或本机访问。');
  if(!config?.key) throw locationError('AMAP_NOT_CONFIGURED', '增强定位尚未配置。');
  const AMap=await loadSdk(config,env);
  return new Promise((resolve,reject)=>{
    let settled=false;
    const finish=(error,point)=>{if(settled)return;settled=true;env.clearTimeout(timer);error?reject(error):resolve(point);};
    // Bound missing plugin callbacks as well as provider-reported timeouts.
    const timer=env.setTimeout(()=>finish(locationError('AMAP_CALLBACK_TIMEOUT', '高德在等待时限内没有返回定位结果，具体失败原因未知。')),18000);
    try {
      const locator=new AMap.Geolocation({enableHighAccuracy:true,timeout:12000,convert:true,
        getCityWhenFail:false,showButton:false,showMarker:false,showCircle:false});
      locator.getCurrentPosition((status,result)=>{
        if(status!=='complete') {finish(describeAmapFailure(result));return;}
        try {finish(null,parseAmapPosition(result));} catch(error){finish(error);}
      });
    } catch {finish(locationError('SDK_REQUEST_FAILED', '高德定位调用未能启动。'));}
  });
}
