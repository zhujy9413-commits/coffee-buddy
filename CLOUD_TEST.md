# 独立 HTTPS 完整测试版

状态：部署文件已准备；尚未创建云端服务或上传云端密钥。

## 服务与数据

- Render Web Service，Docker 运行现有 Python 后端，新加坡区，`plan: free`。
- `render.yaml` 关闭自动部署，不创建付费数据库、磁盘或其他服务。
- 全站使用 HTTPS 和测试访问凭据；用户名为 `coffee`，密码由 Render 随机生成。
- 云端从空 SQLite 数据库开始。镜像只复制明确列出的源文件，不包含 `.env`、`data/`、轨迹或临时访问凭据。
- 测试记录保存在云端临时磁盘。休眠、重启或重新部署会丢失；页面和备份区均提示及时导出。适合功能测试，不作为长期记录库。
- 不同浏览器仍通过 Cookie 分开保存记录；访问密码是测试入口保护，不是正式用户账户系统。

## 功能与权限

保留手动记录、口味设置、咖啡类型管理、三种推荐策略、地点搜索和导入导出。查店需要高德 Web 服务 Key。照片识别暂未配置，仍可选照片后手动填写。

手机点击“使用当前位置”后才申请系统定位。得到的 WGS84 坐标通过 HTTPS 到 Render 后端，再交给高德转换和查店；当前坐标不写入数据库。低精度结果仍需确认，手动地点搜索可作为替代入口。真实 iPhone 定位和国内网络访问尚待部署后验证。

此云端方案不配置高德 JS SDK 密钥、安全密钥或 `AMAP_JS_ALLOW_EVAL`；手机直接使用设备定位，无需加载高德定位 SDK。

## 部署参数

1. 连接 Render 和 GitHub 仓库，核对仅使用 `Free` 实例，不开通付费资源。
2. 使用仓库根目录 `render.yaml` 创建服务，构建文件为 `Dockerfile.preview`。
3. 在云端环境变量填入 `AMAP_API_KEY`（Web 服务平台），禁止写入源码、提交或日志。Render 自动提供 `RENDER_EXTERNAL_HOSTNAME` 和 `PORT`。
4. `PREVIEW_PASSWORD` 通过 `generateValue: true` 生成，仅在受保护的环境变量界面查看。若手动创建服务，必须填入至少 32 位随机密码。
5. 健康检查 `/healthz` 只返回 `{"ok": true}`，不创建浏览器身份；所有页面、脚本和业务接口均要求访问密码。
6. 上线后验证：无密码返回 401、健康检查成功、记录为空、地图 Key 不出现在响应中；使用公开测试地标查店、保存再导出一条测试记录；最后由用户在 iPhone Safari 允许定位并核对结果。

## 费用与停止

Render 免费实例闲置 15 分钟后休眠，重新访问通常需要约一分钟唤醒。构建和带宽受账号额度限制；若账号绑定付款方式，超额可能收费。部署前核对账号预算，不默认升级付费实例。

测试结束后在 Render 暂停测试服务；暂停或重建前先导出要保留的测试记录。不要删除本机 `data/web`。

官方依据：[免费限制](https://render.com/docs/free)、[Web Service](https://render.com/docs/web-services)、[Blueprint 参数](https://render.com/docs/blueprint-spec)。
