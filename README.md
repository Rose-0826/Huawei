# 雾镇 · AI 原生推理桌游

> 北京邮电大学第一届人机协作编程大赛 参赛作品
> MVP v0.1 —— 单人侦探视角的 AI 推理桌游

## 一句话

**每个 NPC 只知道一部分真相。有人撒谎，有人只是记错了。**

## 目录

```
E:\huawei\                   # 项目根目录（码道工程目录）
├── docs/
│   ├── 00_方案说明.md      产品定位 / 玩法 / 评分映射 / 答辩话术 / 演示脚本
│   ├── 01_技术方案.md      架构 / 数据模型 / 核心算法 / API / 前端 / 部署
│   ├── 02_剧本Schema.md    剧本字段规范 / 校验规则 / 新增剧本流程
│   └── 03_码道开发剧本.md  分 7 段的码道 Prompt，逐段复制执行
├── project/                代码本体（在码道里从零生成）
│   └── data/
│       ├── scripts/
│       │   └── mistvale-inn.json   剧本《雾镇旅馆》（5 角色 / 23 事实 / 8 线索）
│       └── regression/             30 条一致性回归用例
├── proof/ai-trace/         码道使用痕迹（脚本自动导出）
├── video/                  演示视频
└── tools/
    └── export_traces.py    会话痕迹导出器
```

## 开工顺序

1. 读 `docs/00_方案说明.md` 的第 4 节（MVP 范围），确认要做什么、不做什么
2. 读 `docs/02_剧本Schema.md`，理解 `holders` 和 `belief` 这两个字段
3. 打开码道，工程目录选 `project/`
4. 按 `docs/03_码道开发剧本.md` 的第 1 段开始，**一段一段喂，别一次性全给**

## 收尾

```bash
python tools/export_traces.py -o proof/ai-trace
```

# 交付四件套

- [ ] 方案说明（`docs/00` 改造成 PPT）
- [ ] 演示视频（脚本见 `docs/00` 第 7 节）
- [ ] 源码（`project/`，含 README + deploy.md）
- [ ] 使用痕迹证明（`proof/ai-trace/` + 截图 + git log）
