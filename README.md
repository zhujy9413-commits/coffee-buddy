# 咖啡探索搭子 · Coffee Buddy

记录咖啡菜单与饮用体验，根据个人风味、烘焙和饮品偏好，提供有来源、可解释的店铺与产品候选。

## 当前状态

文档更新于 2026-10-28，反映已部署的运行源码 `9bdc41c`。本次补充 Windows 兼容验收脚本和文档，运行程序未重新部署。

- 支持手动录入、照片识别草稿、1—20 款批量豆单及逐款人工核对。
- 菜单标注与实际饮用感受分别保存；明确区分喜欢、一般、还说不准和不太喜欢。
- 支持就近原则、口味原则和指定目的地；未知店铺产品、配方和当前在售情况不推测。
- 云端使用个人账号登录和独立 PostgreSQL 数据库，支持跨设备取回记录与偏好；已移除共用测试入口密码。
- iPhone 可通过 Safari 添加到主屏幕，显示“咖啡搭子”图标；使用时需要联网。
- 照片识别和实时找店要求登录，并有持久化的账号及全站请求上限。
- Windows Server 2022 云端环境中的 Chrome、Edge 均完成隔离浏览器验收，每款 47 项检查通过；范围及局限见[电脑端兼容验收](DESKTOP_TEST.md)。

这是用于个人及小规模朋友试用的网页产品。真实复杂菜单识别、推荐的长期帮助程度和多人持续使用效果仍需验证。

## 本机运行

```sh
python3 web_app.py --port 8765
```

浏览器打开 <http://127.0.0.1:8765/>。本机基础记录使用 Python 标准库和 SQLite；地图与照片识别可选，配置见 [本机开发](WEB_DEV.md)。本机访客流程与云端个人账号要求分别说明，不把本机服务直接暴露到公网。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [PRD](PRD.md) | 当前需求、规则及验收边界 |
| [开发进度](PROGRESS.md) | 已交付能力和验证结果 |
| [开发交接](SESSION_HANDOFF.md) | 当前维护起点与后续工作 |
| [云端运行](CLOUD_TEST.md) | 个人登录、外部服务上限与发布检查 |
| [个人账号](ACCOUNTS.md) | 注册、跨设备、恢复码与会话 |
| [免费持久保存](FREE_STORAGE.md) | PostgreSQL、导出恢复与故障行为 |
| [照片识别](PHOTO_RECOGNITION.md) | 识别草稿和人工核对 |
| [批量豆单](MENU_BATCH.md) | 文本格式、逐款确认和整批保存 |
| [口味闭环](TASTE_LOOP.md) | 反馈、分店关联和推荐依据 |
| [手机使用与验收](PHONE_TEST.md) | 主屏幕、权限和真机验证 |
| [电脑端兼容验收](DESKTOP_TEST.md) | Windows Chrome、Edge 流程与桌面布局证据 |
| [可选磁盘方案](PERSISTENT_STORAGE.md) | 未启用的另一种存储方案 |

## 开发检查

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-cloud.txt pytest
.venv/bin/python -m pytest -q
node --test test_location.mjs test_amap_location.mjs test_journal.mjs test_menu_drafts.mjs
```

PostgreSQL 合同测试使用独立测试数据库，通过 `COFFEE_TEST_POSTGRES_DSN` 配置；未配置时相应检查跳过。GitHub CI 提供隔离 PostgreSQL，不能用生产数据库执行测试。

原 `agent.py` 命令行入口保留；它与网页使用不同的数据路径，不自动合并原 CLI JSON。配置示例见 `.env.example`，真实配置、数据库、照片、备份和个人资料不进入仓库。
