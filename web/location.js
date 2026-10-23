export function getLocation(env = globalThis) {
  return new Promise((resolve, reject) => {
    if (!env.isSecureContext) return reject(new Error('手机定位需要 HTTPS 访问。你也可以手动选择地点。'));
    if (!env.navigator?.geolocation) return reject(new Error('当前浏览器不支持定位，请手动选择地点。'));
    env.navigator.geolocation.getCurrentPosition(
      p => resolve({lat: p.coords.latitude, lng: p.coords.longitude, system: 'wgs84', accuracy: p.coords.accuracy}),
      e => reject(new Error(({1: '没有获得定位权限。可以在浏览器设置中修改，或手动选择地点。', 2: '暂时无法获取位置，请手动选择地点。', 3: '20 秒内未能获取位置。请检查系统和浏览器的定位权限，或手动选择地点。'})[e.code] || '定位失败，请手动选择地点。')),
      {enableHighAccuracy: false, timeout: 20000, maximumAge: 60000}
    );
  });
}
