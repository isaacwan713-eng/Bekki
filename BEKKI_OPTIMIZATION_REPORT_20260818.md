# Bekki 源码优化与 Skills V1 验收报告

## 本版完成内容

- 当前请求优先：UI 已保存的当前用户消息会从“历史上下文”中结构化排除，
  content workflow 再由 AI 判断 `CURRENT_ONLY` 或 `NEEDS_CONTEXT`。
- checkpoint 隔离：旧的“继续安装”候选不会接管一个完整的新命令；只有活动
  checkpoint 携带的精确候选 ID 才能恢复 pending Skill。
- checkpoint 原子转移：“继续”不会提前清空旧 checkpoint。context/stage/worker
  暂时失败时保留同一 ID；retry、CAPTCHA 或结果验证 checkpoint 成功写入后才接管，
  只有候选不存在、scope 无效或流程明确完成时才消费旧 checkpoint。
- Skills Registry V2：folder、install 等能力拥有独立 scope；pending、verified、
  rejected、expired 状态严格分离；JSON 使用原子替换、fsync 和 `.bak` 恢复。
- 验证后学习：研究成功或文件夹打开成功都只会产生临时候选。必须同时有机器执行
  成功记录和用户明确确认，才会写入 verified Skills。失败、CAPTCHA、取消、拒绝、
  错误目录或不完整记录都不会入库。
- 首个 folder Skill：`OPEN_DESTINATION_FOLDER` 与下载/安装、推荐完全分离。
  推荐卡片和链接永远不会被保存为 Skill。
- AI / Python 边界：AI 负责意图、阶段、上下文引用、应用身份、适配器与目标选择；
  Python 只检查 closed enum、opaque ID、scope、文件类型、目标边界和生命周期。
- 输出可靠性：Balthasar、Melchior、confirmation、content stage、checkpoint 和
  resume 均使用不同提示词/模型的有界重试，避免同一个小 token 合同连续返回空值。
- 通用提示去偏置：通用 content research/query prompts 不再嵌入 FM26 或曼联示例；
  `CURRENT_REQUEST` 是唯一任务权威，跨应用示例只用于说明结构。
- 学习计划与查询防污染：独立 grounding AI 会先核对应用、内容类型、scope 和
  可复用结果确实来自当前请求，拒绝从跨应用示例、schema 或旧任务复制的身份。
  首次通过核对的计划会被保留；缺失或被 focused AI 拒绝的文档搜索词只会由
  独立 query AI 重做，不会重新生成整份计划。占位文本、旧任务偏好与泛化元文本
  都不能进入浏览器。
- 搜索引擎：内容工作流使用 rendered browser，多搜索引擎由 AI 按任务和地区选择；
  没有 Bing、Google 或 DuckDuckGo 的全局硬编码默认值。地区来源、置信度和时区
  会进入 AI packet；Python只按 catalog 的 availability 与 regional audience 元数据
  阻止跨地区引擎，并在日志中输出 country-level 检测结果。
- Qt 字体：应用创建时设置有效的 10pt 字体，避免 Windows 上继承 `-1` point size。
- `.env`、`data/`、浏览器 profile、build/dist 和缓存均未纳入更新内容。

## 自动验证

从项目根目录执行：

```powershell
python -m unittest discover -s tests
python -m compileall -q .
```

本次容器验证结果：完整套件共 256 项，252 项通过，4 项真实 Ollama smoke tests
按设计跳过；全部 Python 文件通过 compileall。

真实模型测试需要在安装了 Ollama 模型的 Windows 电脑上执行：

```powershell
$env:BEKKI_LIVE_AI_TESTS = "1"
python -m unittest -v tests.test_live_ai_contracts
Remove-Item Env:BEKKI_LIVE_AI_TESTS
```

## Windows 手动验收

1. 在项目根目录运行 `python main.py`。
2. 输入一个完整的新命令，例如“打开 FM26 战术文件夹”。
3. 确认日志和搜索没有继承之前的曼联战术安装条件。
   同时检查 `[CASPER SEARCH REGION]` 的国家/时区信号是否符合本机设置。
4. 检查打开的目录；正确时回答“打开对了”。此时 folder Skill 才能 verified。
5. 换一种说法再次要求打开同一目标目录，确认 Bekki 直接复用 verified Skill，
   不再重复上网学习。
6. 故意回答“不是这个文件夹”，确认候选被丢弃而不是写入 Skills。
7. 在学习 checkpoint 出现时回复“继续”，确认请求会恢复到原始完整任务，且不会因
   `DONE REASON: length` 的第一次空输出直接结束。

## 当前边界

Skills/registry/workflow 已经是通用架构，但首个可执行本地 content adapter 仍是
`FM_TACTIC`（只允许 `.fmf` 和已发现的 FM tactics destination）。未来新增 Chrome
扩展、Minecraft mod、软件安装或 Steam 购买，应增加各自独立 adapter 与 protected
event 边界；不能把 `.jar`、`.exe` 或付款流程塞进 FM adapter。

本容器没有 Windows Explorer、Qt Windows 样式或用户本机 Ollama，因此文件夹真实
打开、字体警告消失和模型输出需要按上面的 Windows 步骤做最终现场验收。

两个非阻塞的安全边界仍保留：verified 目录后来被移动或删除时会 fail closed，但本版
不会自动废止该 stale Skill；机器执行成功后若程序恰好在保存用户确认 checkpoint 前
崩溃，候选不会误入 verified Skills，但用户可能需要重新发起一次学习流程。
