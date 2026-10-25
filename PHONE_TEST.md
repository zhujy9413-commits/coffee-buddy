# iPhone 定位测试准备

更新日期：2026-10-25。当前状态：本次临时隧道和手机测试后端已关闭，旧链接与密码不再提供访问；用户选择保留 VPN，不改网络设置。手机优先系统定位的改动已保留，真实 iPhone 定位仍未验证成功。此前 HTTPS 访问保护检查曾通过，后续隧道连接失败。

## 已核实的诊断

- 内置浏览器实际定位返回 `IP_LOCATION_FAILED / BROWSER_TIMEOUT`：IP 定位失败，同时浏览器设备定位超时。这描述的是失败环节，尚不能锁定系统或网络的单一根因。
- 浏览器中以高德 SDK 转换公开测试坐标成功，验证 JS API 配置与该安全代理链路。手工拼接同一接口曾返回 `USERKEY_PLAT_NOMATCH`，而 SDK 调用成功，因此该手工结果不作为 Key 配错的依据。
- 新错误提示分别识别组件加载、网页安全环境、系统/网站权限、超时、位置不可用、Key 平台/安全码/域名及调用额度问题。仅显示已知错误码和固定说明，不直接显示高德原始返回内容，避免带出密钥、请求地址或坐标。

## 本次已批准的开放范围

- 仅开放 `phone_preview.py` 的独立测试服务，监听 `127.0.0.1:8770`；电脑原来的 8765 服务保持本机使用。
- 使用 Cloudflare Quick Tunnel 生成临时 HTTPS 地址。所有页面、脚本、记录接口和地图代理都要求本次随机访问密码，不把随机网址当作访问保护。
- 测试数据库固定为 `data/phone-preview/coffee.sqlite3`，不读取或复制 `data/web` 的现有记录和偏好。手机测试新写的记录留在该独立数据库中。
- 密码每次启动重新生成，只写入本机 `data/phone-preview/access.txt`，权限 600；不输出到聊天或隧道日志。测试后端一小时自动停止接收请求，再次启动旧密码失效。关闭隧道进程可立即撤掉 HTTPS 地址。
- 私有 Web 服务 Key 和 JS 安全密钥继续留在本机后端；JS API Key 按官方设计提供给浏览器。SDK 沿用当前兼容开关，若启用则允许已获准脚本动态执行代码；不开放任意脚本来源。
- 手机网页请求会经 Cloudflare 中转。点击“使用当前位置”时，位置查询将经过 Cloudflare 到达本机，并由高德处理；项目不保存当前位置。Cloudflare 是这一步新增的第三方中转服务。

2026-10-25 用户明确回复“允许”，批准本次一小时临时 HTTPS 入口、Cloudflare 中转及沿用高德 SDK 兼容开关。该授权不等于正式上线或持续对外服务。

## 执行顺序与当前验证

1. 使用本次工作区已校验的官方 `cloudflared`，不设置系统后台常驻服务。本机路径为 `/Users/zhujiayi/Documents/Codex/2026-10-23/wo-z/work/phone-test-tools/cloudflared`，版本 2026.10.3。
2. 启动临时隧道：

   ```sh
   /Users/zhujiayi/Documents/Codex/2026-10-23/wo-z/work/phone-test-tools/cloudflared tunnel --url http://127.0.0.1:8770
   ```

3. 取得本次实际 HTTPS 地址后，在项目目录启动受保护后端，以下示例地址需替换为本次地址：

   ```sh
   python3 phone_preview.py --origin https://实际名称.trycloudflare.com
   ```

4. 先验证：未提供密码访问首页/API 被拒绝；密码正确后可加载页面；HTTPS Cookie 带 Secure；手机测试库为空；原电脑记录保持不变。若 Key 有域名限制，只将本次具体测试域名加入相应配置，不移除现有保护。
5. 用户在 iPhone 的 Safari 打开 HTTPS 链接，使用本机凭据文件中的用户名与密码。先确认页面正常，再点击一次“使用当前位置”，按系统提示允许定位。若是估算结果，核对后再确认。
6. 记录成功或失败的诊断代码，不保存实际坐标和密码；完成后关闭后端与隧道。不可通过忽略证书警告、信任自签名根证书或关闭安全限制来代替 HTTPS。

实际 HTTPS 检查已确认：首页、记录接口与地图代理无密码均返回 401；登录后页面和新定位模块可加载，手机测试记录为空，定位提供方为高德，Cookie 带 Secure；私有配置、原数据库和访问密码文件均不可通过网页下载；原电脑数据库逻辑指纹保持一致。当前尚未验证 iPhone GPS。若手机也失败，按新错误码继续定位原因，而非默认更换 Key、充值或反复延长超时。

## iPhone 首次反馈与修正

用户首次截图为 `SDK_LOAD_TIMEOUT`，尚未进入设备定位，不代表 iPhone GPS 已失败。手机端已改为直接申请系统定位，绕过 SDK 加载依赖；取得 WGS84 坐标后仍由高德 Web 服务在后端转换和查店。权限拒绝时不自动改用 IP 定位。

后续检查发现旧临时入口返回 Cloudflare 1033，已在本次授权内安排恢复。新入口仍沿用原密码和独立数据库，原定北京时间 12:10 到期；具体当前链接见本机 `data/phone-preview/access.txt`。请在 iPhone 打开更新后的链接，以加载新版本，系统定位结果仍需真机复测。

## 参考

- [高德定位失败流程与 message 字段](https://lbs.amap.com/faq/js-api/map-js-api/position-related/43361)
- [高德 JS API 错误码](https://lbs.amap.com/api/javascript-api-v2/guide/abc/errorcode)
- [高德安全密钥的后端代理](https://lbs.amap.com/api/javascript-api-v2/guide/abc/jscode)
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

## 本次隧道恢复结果

QUIC 超时后尝试官方支持的 HTTP/2，后者返回 `TLS handshake with edge error: EOF`，公开入口仍返回 Cloudflare 530/1033。失败的隧道均已停止，不能把这些链接当作可用入口交付。当前移动端代码已通过 16 项 JavaScript 检查；使用公开 WGS84 坐标在独立本机后端完成转换与附近店铺查询，返回 25 家候选。

只读检查中，系统 HTTP/HTTPS/SOCKS 代理开关和常见代理环境变量均未开启，但 Cloudflare 隧道域名解析到了 `198.18.0.0/15` 地址段。单次 TCP 7844 连接可建立，不能简单认定端口完全被禁；真实 TLS 隧道握手仍失败。代理/TUN/Fake-IP 仅为待验证线索，尚未修改 DNS、VPN、代理或防火墙，等待用户说明实际网络环境。

手机系统定位真机复测仍未完成。旧隧道当前不可用；后续若重建，继续使用原批准的截止时间，过期后先说明状态再安排测试。

2026-10-25 用户确认电脑开启代理。只读查看 Clash Verge，确认虚拟网卡（TUN）和全局模式均开启；尚未证明其为 SDK 超时或隧道 TLS 失败的根因。没有更改代理、TUN、节点、DNS 或规则。建议用户自行短暂关闭 TUN 后通知，再做对照；需考虑当前聊天联网可能中断。原批准的临时公网窗口仍于北京时间 12:10 截止，不自动延长。

用户随后选择“保留 VPN，暂不改网络设置”。已按此约束停止本次隧道恢复排查，并关闭闲置的独立手机测试后端；原 8765 服务保留，原有数据与独立测试数据均未删除。此次临时链接及密码不再提供访问。移动端优先系统定位的代码与 16 项 JavaScript 检查、公开坐标查店结果已保留，但真实 iPhone 定位仍未验证成功。后续可准备独立 HTTPS 测试环境，实际部署须先确认对象及影响。
