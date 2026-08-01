# CrossAudit v2

**一个对话面,两个互相制衡的 agent,一本可回放的账。**
**One conversation, two adversarial agents, one replayable ledger.**

你用平常的话说需求。程序把每句话分拣给执行端、审计端或账本,两个来自不同厂商
的模型互相盯着干活,整条监督史落进 git——出了问题能追到是谁、什么时候、按哪
一版规则。

You speak plainly. The program sorts each sentence to the generator, the
auditor, or the ledger; two models from different vendors keep each other
honest; and the whole supervision history lands in git, so when something goes
wrong you can say who, when, and under which version of the rules.

> 设计核心见 **[DESIGN.md](DESIGN.md)**(中英对照)。协议本身与其论文在
> [crossaudit](https://github.com/dongzhaohe321418-lab/crossaudit)(v1,研究记录)。
> The design core is **[DESIGN.md](DESIGN.md)**; the protocol and its paper live
> in v1.

## 安装 Install

```bash
pip install "crossaudit @ git+https://github.com/dongzhaohe321418-lab/crossaudit_v2@main"
```

装完什么也不会发生——不联网、不认证、不写任何东西。所有交互都在 `init` 之后。
Installing does nothing: no network, no auth, no writes. Everything interactive
lives behind `init`.

## 三分钟上手 Three minutes

```bash
crossaudit init my-project
```

建目录、`git init`、忽略本地状态目录,它一并做掉——**审计读的是 commit,所以
不是仓库的项目根本没法审**。已在别处建好了就直接 `crossaudit init`。

界面是方向键选择的终端向导(零依赖,stdlib 画的);**管道输入、CI、Windows 无
termios 时自动退回默认值,绝不卡在一个永远不会到来的按键上**。

向导问四件事:谁审计、谁生成(两家必须不同,否则拒绝)、两个 API key、
**以及你的项目是什么、你最怕出什么错**。最后一问是关键:你说人话,系统把它
蒸馏成编号的审计规则,展示给你看,你点头才落盘。**你从头到尾不用写 markdown。**

The wizard asks four things: who audits, who generates (must be different
vendors, or it refuses), the two API keys, **and what your project is and what
you are most afraid of getting wrong**. That last answer is distilled into
numbered rules, shown to you, and committed only if you agree. You never write
markdown.

然后说一句要什么,循环自己转起来:

```bash
crossaudit build "写一节关于光伏度电成本的内容,数字必须和数据文件一致"
```

```
  ── round 1 ──
  generator  3 file(s): work/lcoe/SUMMARY.md, …
  auditor    blocked
             [CA-TXT-001] 正文写 0.052,而数据文件是 0.044
  loop       findings returned to the generator
  ── round 2 ──
  generator  3 file(s)  note: 已按数据修正正文
  auditor    passed
  Done in 2 round(s).
```

执行端写、审计端判、findings 打回去重写,直到通过或交给你。每一轮都是 commit,
每次裁定都有报告和回执。**Say what you want; the loop writes, audits, and
revises until it passes or hands it to you.**

其余时候也只有一个动作——说话:

```bash
crossaudit talk "以后严查每个数字的来源"      # → 改标准,起草修宪,确认后提交
crossaudit talk "第三节太啰嗦了,压缩一下"     # → 改内容,交给执行端
crossaudit talk "现在怎么样了"                # → 只读查询,从账本回答
crossaudit talk "那次拦错了,0.052 是引用原文"   # → 争议:回审计端重读一次,它自裁
```

程序自己判断这句话属于哪条车道。**拿不准就问,绝不猜。**

The program decides the lane. **When unsure it asks; it never guesses.**

## 定制执行端 House skills

给执行端写 skill,让产出长成这个项目要的样子:

```bash
crossaudit skills --new house-style   # 写一份模板
crossaudit skills                     # 看当前生效的
```

`skills/*.md` 是你的行文风格、领域惯例、范例、完成前的检查步骤;front-matter 里
可选 `applies_to: work/` 限定它在哪些回合生效。

**边界是硬的**:skill 改变执行端*怎么写*,绝不改变它*能写到哪*、*由谁判*。
审计端永远看不到 skill——能对审计端说话的 skill 就是一条没人同意过、没有版本的
规则。skill 说"你也可以改规则文件"也没用:路径守卫才是裁决者,那一轮会被当场
打回(循环自己继续,不崩)。skill 的哈希进回执,换了 skill 就是另一轮。

A skill shapes how the generator works, never what it may touch or who judges
it. The auditor never sees them; the path guard, not the text, decides where the
generator may write; and their hashes go into the receipt.

## 浏览器里的黑箱 The box, in a browser

```bash
crossaudit console            # 后台常驻,关窗口不影响它
crossaudit console --status   # 在跑吗?URL 是什么
crossaudit console --stop     # 停掉
```

**关掉窗口 build 照跑**,再执行 `crossaudit console` 会**重连**回同一个 URL,
接着看。守护进程被强杀(断电、误关)后重开,会如实告诉你"上次有一个 build 被
打断"——账本里已提交的轮次一条不少,被切断的那一轮不在里面。

The console outlives the window: builds keep running, `crossaudit console`
reattaches to the same URL, and if the daemon was killed mid-build the next one
says the build was interrupted rather than letting a half-finished loop read as
finished.

**执行端主窗 · 审计端副窗 · 底部一个输入框**。你像对任何 AI 一样打字,程序决定
这句话该给谁——"把主题改成储能成本"去左窗(执行端整轮开工),"以后审计重点放在
来源版本上"去右窗(起草修宪并提交)。判定与置信度就显示在输入框上方,你自己的话
也会出现在**听见它的那一侧**。

Two windows — the generator's work on the left, the auditor's judgement on the
right — and one input at the bottom. Type as you would to any assistant; the box
decides which side hears it, and shows you the decision and how sure it was.

打开是一块一眼能读懂的面板:**指标带**(审计数 / 通过 / 拦截 / 等你处理 /
已准入)、**五步流水线**(提交 → 检查 → 审计 → 裁定 → 准入,逐格着色)、
**执行端与审计端两个对话窗**、以及**等你处理 / 规则抓到了什么 / 争议**三张卡。
底部仍然是那一个输入框。

数据**实时推送**——服务端只在状态真的变了才发一帧,连接状态在右上角亮着;
断线自动退回轮询。

An overview you can read at a glance: a metric band, the five steps of the loop
with each one coloured by what actually happened, the two conversations, and
what is waiting on you. Updates are pushed the moment anything changes.

说完就能**看着它干活**:生成端写了哪些文件、审计端拦在哪条规则、findings 打回去
第几轮、计时多少秒——逐步出现,不用等整轮跑完。进度只在内存里,随进程消失;
记录始终是账本。

Watch it work: which files the generator wrote, which rule the auditor blocked
on, which round the findings went back to, and how long it has been running.
Progress is in memory and vanishes with the process; the record is always the
ledger.

回环绑定、每个请求要 token、Host 校验、无 cookie、严格 CSP、密钥只报有无。
唯一的写入路径就是那个输入框,而它能引发的一切,CLI 本来就能做。

## 打开箱子 Opening the box

外壳不透明是为了好用;内胆是玻璃做的:

```bash
crossaudit skills      # 执行端的外置技能:生效范围与哈希
crossaudit console     # 浏览器只读窗口:周期、路由、争议、真实准入档位
crossaudit routing     # 每一次路由决定:原话、车道、置信度、实际执行了什么
crossaudit watch       # 执行端与审计端的往来对话,从账本重建
crossaudit status      # 每个周期的状态
crossaudit verify <receipt>   # 逐项重新推导回执的每个绑定
```

路由决定本身也入账——否则路由器就成了第三个不受审计的 agent。
The routing decision is itself a ledger entry; otherwise the router would be a
third, unaudited agent.

## 引擎动词 Engine verbs

对话面之下是 v1 的引擎,照旧可以直接用:

```bash
crossaudit run       # 审计最新提交:确定性检查 → 模型审计 → 报告 + 回执
crossaudit check     # 只跑确定性检查层,不碰任何模型
crossaudit amend "…" # 直接修宪(等于 talk 的 amendment 车道)
crossaudit resolve <cycle> --reopen --because "…"   # 人类裁决升级
crossaudit pair --apply                              # 建双仓:权限分离
crossaudit doctor --fix                              # 体检并逐条指路
```

退出码是契约:`0` 好结果 · `10` BLOCKED · `11` 升级或仅确定性层 ·
`20` 配置/环境 · `21` 回执完整性 · `22` provider。所有命令支持 `--json`。

Exit codes are contract; every command supports `--json`.

## 不只是科研 Not only for research

八条不变量没有一条提到"科学"。**产出能落成文件、标准能说得成规则**,就能跑:
代码、合同审查、财务模型、文案、数据管道。领域相关的只有确定性检查包(可插拔)
和规则内容(由你的话生成)。没有现成检查包的领域,确定性层贡献为零、模型审计
独自扛——这一点程序会明说,不含糊。

None of the invariants mentions science. If the output can be a file and the
standards can be stated as rules, it runs. Where no domain check pack exists,
the deterministic layer contributes nothing and the model audit carries the load
alone — the program says so rather than glossing over it.

## 它会说自己够不着的档位 It names the tier it cannot reach

```
crossaudit doctor
  [PASS] admission tier   local — self-review; the history is yours to rewrite
  [PASS]   toward enforced  the history can be rewritten by whoever holds it
```

四档:`local` 只能自省 · `remote` 历史脱离单方控制 · `paired` 两个 agent 之间
可互相追责 · `enforced` 审计不过就拒绝合并。**enforced 要四件同时成立**,而且
全部实测:controller 自己跑一次锁来证明持久与原子,分支保护由 `gh` 读真实规则。
差一件就诚实降级为 `verified-notification`——"发布裁定"不等于"拒绝合并"。

Four tiers, and it tells you the one you are actually at. "Enforced" requires
four things at once, each probed rather than inferred; anything less is named
`verified-notification`, because publishing a verdict is not refusing a merge.

## 为什么必须 git Why git is mandatory

追责的四个要件都由 commit 提供:审的是什么(SHA + tree 哈希)、审后有没有被改
(回执 manifest 重推导)、谁和何时(作者链)、报告与回执孰先孰后(提交顺序)。
所以审计只审**已提交内容**,永不审工作区。v2 里 commit 是箱内动作——执行端
自己提交,你不必碰 git。

分析用本地仓就够;**追责需要历史脱离单方控制**(本地历史你自己能 rebase 掉),
GitHub 只是最方便的实现。再上一级是双仓 + 权限分离——那不是为了科研,是为了
让两个 agent 之间也能互相追责。

Accountability needs all four: what was audited, whether it changed afterwards,
who and when, and the ordering of report and receipt. Local git suffices for
analysis; accountability needs the history out of unilateral control; and the
paired-repository tier exists for privilege separation between the two agents.

## 状态 Status

`2.0.0`. 已落地:对话式宪法蒸馏、路由器(六车道全通)、`build` 闭环、
**争议车道**(一次性、审计端自裁)、**领域中立检查包**(4 项,非科研可用)、
**检查包插件**(allowlist + API 版本校验)、**`pair` 双仓向导**(先 plan 后 `--apply`)、
**准入档位自证**(四档,平台实测而非配置声明)、**`console` 只读控制台**
(stdlib 零依赖、回环、token、Host 校验、结构上无写入路径),以及 v1 的完整引擎。
下一步:独立安全复核、真实 enforced 部署证据、PyPI 发行。
路线图见 [DESIGN.md §8](DESIGN.md)。

Landed: everything through 2.0 — spoken rules, the six-lane router, the closed
build loop, the one-shot dispute channel, domain-neutral checks, allowlisted
plugins, the paired-repository wizard, evidence-based admission tiering, and the
read-only console. Next: independent security review, evidence from a real
enforced deployment, and PyPI distribution.

## 许可 License

[MIT](LICENSE) © 2026 Zhaohe Dong, Yuhao Chen
