# 本机网页开发

更新于 2026-10-28。本机使用 SQLite，云端采用独立 PostgreSQL 与个人账号；两者的数据不会自动互传。当前云端状态见 [CLOUD_TEST.md](CLOUD_TEST.md)。

## 运行与维护源

在当前检出的仓库根目录运行：

```sh
python3 web_app.py --port 8765
```

浏览器打开 <http://127.0.0.1:8765/>。本机入口默认只监听回环地址，基础记录使用 Python 标准库。网页数据位于被 Git 忽略的 `data/web/coffee.sqlite3`；原 CLI 的 JSON 不自动迁移。

本机支持访客流程及个人账号，浏览器 Cookie 决定身份；不同主机名、浏览器和临时测试页可能使用不同身份。看不到记录时先核对账号与身份，不能直接判断数据库丢失，也不能用测试页覆盖个人 Cookie。

## 可选配置

从 `.env.example` 创建私有 `.env`，已有配置时仅补缺项。开发服务启动时读取，修改后需重启。

- `AMAP_API_KEY`：高德 Web 服务，供服务端查地标、转换坐标及查店。
- `VISION_ENDPOINT`、`VISION_API_KEY`、`VISION_MODEL`：支持图片输入的兼容接口、凭据和模型；地址须为完整 HTTPS chat-completions 接口。
- `AMAP_JS_API_KEY`、`AMAP_JS_SECURITY_CODE`：仅本机可选融合定位的一对配置；未配齐时用设备定位。
- `AMAP_JS_ALLOW_EVAL`：默认关闭；只有配齐本机 JS 凭据并显式选择兼容开关时才放宽该脚本限制，云端不配置它。

所有示例只写变量名，真实值留在私有配置。服务未配置时手动录入、筛选及已有资料推荐仍可用，不把普通文本模型当作图片模型。

## 功能与隔离

三页分别是去哪喝咖啡、记一杯、我的记录；偏好、分类、照片核对、批量事务和反馈规则与云端共用实现。独立演示使用 `demo_app.py`、自己的数据库与 Cookie，测试产品明确标为虚构；不读取个人库，也不请求真实定位或地图。

云端入口使用 `require_account=True`，新访客需登录后写入或调用外部服务；本机默认访客行为保留。不要把本机服务直接开放公网，手机在线试用使用已配置的 HTTPS 云端版本。

## 检查

```sh
python3 -m pytest -q
node --test test_location.mjs test_amap_location.mjs test_journal.mjs test_menu_drafts.mjs
```

完整依赖和隔离 PostgreSQL 配置见 [README](README.md)。真实图片模型、地图或设备定位验收应单独说明，不把模拟响应或公开坐标转换写成读取到设备位置。
