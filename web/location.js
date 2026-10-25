import {getAmapLocation} from './amap-location.js';

function deviceError(code, message) {
  const error = new Error(message + ' 可手动选择地点继续查店。诊断代码：' + code + '。');
  error.code = code;
  return error;
}

function isMobileDevice(env) {
  const navigator = env.navigator || {};
  return /iPhone|iPad|iPod|Android/i.test(navigator.userAgent || '') ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

export function prefersDeviceLocation(config, env = globalThis) {
  return isMobileDevice(env) || config?.provider !== 'amap';
}

export function getCurrentLocation(config, env = globalThis) {
  // Request in the click handler before waiting for any third-party script.
  if (prefersDeviceLocation(config, env)) {
    return getLocation(env, {enableHighAccuracy: isMobileDevice(env)});
  }
  return getAmapLocation(config, env);
}

export function getLocation(env = globalThis, {enableHighAccuracy = false} = {}) {
  return new Promise((resolve, reject) => {
    if (!env.isSecureContext) return reject(deviceError('INSECURE_CONTEXT', '手机定位需要 HTTPS 或本机访问。'));
    if (!env.navigator?.geolocation) return reject(deviceError('BROWSER_UNSUPPORTED', '当前浏览器不支持设备定位。'));
    let settled = false;
    const finish = (error, point) => {
      if (settled) return;
      settled = true;
      env.clearTimeout(timer);
      error ? reject(error) : resolve(point);
    };
    const timer = env.setTimeout(() => finish(deviceError('BROWSER_CALLBACK_TIMEOUT',
      '设备定位未在等待时限内返回结果，具体原因未知。')), 22000);
    try {
      env.navigator.geolocation.getCurrentPosition(
        p => {
          const lat = p?.coords?.latitude, lng = p?.coords?.longitude;
          if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
            finish(deviceError('INVALID_POSITION', '设备返回的位置格式无效。')); return;
          }
          const rawAccuracy = p.coords.accuracy;
          const accuracy = Number.isFinite(rawAccuracy) && rawAccuracy > 0 ? rawAccuracy : null;
          finish(null, {lat, lng, system: 'wgs84', accuracy, approximate: accuracy === null || accuracy > 500});
        },
        e => {
          const failure = {
            1: ['BROWSER_PERMISSION_DENIED', '没有获得设备定位权限，请检查系统与网站定位权限。'],
            2: ['BROWSER_POSITION_UNAVAILABLE', '系统位置服务暂时没有返回可用位置。'],
            3: ['BROWSER_TIMEOUT', '20 秒内未能取得设备位置，系统位置服务或网络可能导致超时。'],
          }[e?.code] || ['BROWSER_POSITION_FAILED', '设备定位失败，具体原因未知。'];
          finish(deviceError(...failure));
        },
        {enableHighAccuracy, timeout: 20000, maximumAge: 60000}
      );
    } catch { finish(deviceError('BROWSER_REQUEST_FAILED', '设备定位调用未能启动。')); }
  });
}
