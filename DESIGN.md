# CrossAudit v2 — 设计核心 · Design Core

> 一个对话面,两个互相制衡的 agent,一本可回放的账。
> One conversation, two adversarial agents, one replayable ledger.

**状态 Status**: v2 设计冻结 2026-08-01,实现进行中。本文件是项目的核心文档;
与它冲突的任何说明以本文件为准,除非本文件被注日期的修订取代。
（Design frozen 2026-08-01, implementation under way. This file is the project's
core document; where anything disagrees with it, this wins, unless superseded by
a dated amendment here.）

---

## 0. 一句话 · In one line

**中文** — v1 证明了协议成立:让另一家厂商的模型审计你的 AI 产出,把整条监督
史写进 git。v2 要证明协议**可用**:把这条环收进一个黑箱,用户只对着一个对话面
说人话,程序自己决定这句话该给执行端、审计端还是账本。

**EN** — v1 established that the protocol works: have a different vendor's model
audit your AI's output, and write the whole supervision history into git. v2
establishes that it is *usable*: the loop goes inside a box, the user speaks
plainly to one conversational surface, and the program decides whether a given
sentence belongs to the generator, to the auditor, or to the ledger.

---

## 1. 为什么要 v2 · Why v2 exists

**中文** — v1 交付了一个正确但陡峭的东西。要用起来,用户必须先理解"增量"
"宪法""回执""周期"这套世界观,还要手写一份 markdown 规则书,再学会一串命令。
对协议研究者这是恰当的;对普通开发者这是一堵墙。v2 的判断是:**把"写规则"
这个动作从产品里删掉,只留下"说要求"和"点头"**。规则不再是用户的义务,而是
系统的产出。

**EN** — v1 shipped something correct and steep. To use it you first had to
absorb a worldview (increments, Constitution, receipts, cycles), hand-write a
markdown rulebook, and learn a command surface. Right for protocol researchers,
a wall for everyone else. v2's judgement: **delete the act of "writing rules"
from the product, leaving only "stating requirements" and "nodding"**. The
rulebook stops being the user's obligation and becomes the system's output.

---

## 2. 产品形态 · The product shape

```
                ┌──────────────────────────────────────────┐
   用户说话 ──▶ │  Router 路由器(程序自己,决定入账)        │
   user speaks  │    ├─ 项目是什么      ──▶ 两端各自建档     │
                │    ├─ "太啰嗦,压缩"   ──▶ 执行端 generator │
                │    ├─ "严查数据来源"  ──▶ 审计端 amendment │
                │    ├─ "那次拦错了"    ──▶ 争议 dispute      │
                │    └─ "现在怎么样了"  ──▶ 只读查询 query    │
                │                                          │
                │    generator ⇄ auditor  (loop 自转)       │
                │            └── ledger 账本(照记不误)      │
                └──────────────────────────────────────────┘
   用户看到 ──▶  "在写了…审计拦了一处来源问题…已修复…完成"
```

**中文** — 外面看是一个 AI,里面跑的是两个互相制衡的 agent 加一本账。用户按
平常语言习惯说话,**分拣这件事的认知负担从用户头上移到程序头上**——这就是
"黑箱"的全部含义。

**EN** — From outside it is one AI; inside are two agents that check each other
and a ledger. The user speaks as they normally would, and **the cognitive
burden of sorting is moved off the user and onto the program** — that is the
entire meaning of "black box" here.

---

## 3. 三条不可让步的柱子 · Three non-negotiable pillars

### P1 — 黑箱是交互的,不是记录的
**Opaque to interact with, glass on the inside.**

**中文** — 外壳不透明,内胆全是玻璃。每句话被路由到哪条车道、执行端每次修订、
审计端每次拦截、路由器每一个判断,全部落账。用户**不必**打开看,但**随时能**
打开看。信任来自"可打开",好用来自"不必打开"。

推论(硬性):**路由决定本身必须入账**。否则路由器就成了第三个不受审计的
agent——一个能悄悄决定"这句话不给审计端看"的东西,正是这个协议存在的理由所要
防范的。

**EN** — Every routing decision, every generator revision, every auditor
finding is committed. The user *need not* look inside, and *can always* look
inside. Trust comes from "can open"; usability comes from "need not open".
Corollary, hard: **the routing decision is itself a ledger entry**. Otherwise
the router becomes a third, unaudited agent — one that could quietly decide
what the auditor never sees.

### P2 — 隔离在箱内保持
**Isolation survives the box.**

> 实现落点 As implemented (a3): 生成端只被交给任务、规则、当前工作与**审计
> findings 的正文**——报告的抬头(哪家厂商判的、哪个 sha)被剥除;生成端的
> 推理与自辩留在它自己那一侧,永不进入审计端的 prompt。生成端可写的目录由
> `scope.dirs` 限定,越界(绝对路径、`..`、隐藏目录、规则文件、配置、账本)
> 一律拒绝——它不能改写审判自己的依据。

**中文** — 主事者(用户)对两端说话都合法:他本来就是规则作者和任务下达者。
必须继续挡住的只有一条红线:**执行端的内部叙事(它的 prompt、它的推理、它的
自辩)不得流向审计端**。路由器转发的是**用户的话**,不是执行端的话。审计端永远
只看已提交的工件。这条是自偏好偏差的入口,写死在实现里。

**EN** — The principal may address both ends; they author the rules and set the
task. One red line remains: **the generator's internal narrative — its prompts,
its reasoning, its self-justification — never reaches the auditor.** The router
forwards *the user's* words, never the generator's. The auditor sees committed
artefacts and nothing else.

### P3 — 对话是入口,账本是形态
**Conversation is the input; the ledger is the form.**

**中文** — 用户说的话是易逝的;系统把它蒸馏成结构化规则、展示、用户点头、
落盘成带 commit 哈希的宪法。审计永远按**落盘的那一版**执行,修订只在周期之间
生效。v1 的教训(I2:只活在模型上下文里的状态事后不可复原)在 v2 里以产品形态
被兑现:**ephemeral 的话进来,versioned 的法出去**。

**EN** — Spoken requirements are ephemeral. The system distils them into
structured rules, shows them, waits for a nod, and commits them as a
version-pinned Constitution. Audits always run against the committed version,
and amendments take effect only between cycles.

---

## 4. 路由器 · The Router

### 4.1 车道 · Lanes

| 车道 Lane | 触发 What it looks like | 落成什么 Materialises as |
|---|---|---|
| `project` | "这是一个 X 项目,我怕 Y" | 执行端任务书 + 审计端宪法底稿(各自落盘) |
| `generator` | "太啰嗦了""补一节关于 Z""这段重写" | 执行端修订指令 → 新增量 commit |
| `amendment` | "以后严查数据来源""这条太严,放宽" | 宪法修订草案 → 确认 → 下一周期生效 |
| `dispute` | "那次拦错了""这个 finding 不成立" | 按 rule ID 的**一次性**争议:带论据回到审计端重读一次,审计端自裁 UPHELD/WITHDRAWN,裁决入账。争规则不是争 finding——那是修宪 |
| `resolve` | "算了,这个就这样吧""放行" | 人类对升级的裁决(I6 的另一半) |
| `query` | "现在怎么样了""为什么被拦" | 只读,从账本回答,不产生任何变更 |

**中文** — 分类由**审计端模型**执行(它对规则的理解最相关),但分类结果本身
是数据,不是命令:落成 `routing.jsonl` 的一条记录,含原话、判定车道、置信度、
以及最终执行的动作。分错了在账本里看得见、可回溯。

**EN** — Classification runs on the auditor-side model, but its output is data,
not command: one line in `routing.jsonl` carrying the utterance, the chosen
lane, the confidence, and what was actually executed. A misroute is visible and
reversible in the ledger.

### 4.2 低置信度的处理 · When the router is unsure

**中文** — fail-closed 的产品版:**拿不准就问,绝不猜**。置信度低于阈值时,
黑箱短暂地不黑——"这句我理解成 A(改内容)还是 B(改标准)?"一句话确认。
这比猜错便宜得多:猜错方向的修订会污染宪法或产出。

**EN** — The fail-closed default, in product form: **when unsure, ask; never
guess.** Below the confidence threshold the box briefly becomes transparent —
one clarifying question. Cheaper than a wrong guess, which would contaminate
either the rulebook or the work.

### 4.3 角色自动分配 · Automatic role assignment

**中文** — 两个 key 在手,系统自动分配谁审谁写,顺手满足 I1(异质性)。默认
规则:两家不同厂商时任意指派并记录;用户一句话可改("让 GPT 来审")。**同厂
配对直接拒绝**——那是同源监督,是这个协议存在的理由所要防范的东西。

**EN** — With two keys present the system assigns roles and satisfies I1 by
construction. Same-vendor pairs are refused outright: that is same-source
supervision, the thing the protocol exists to prevent.

---

## 4.4 House skills 外置技能

**中文** — 用户可以给执行端写 skill(`skills/*.md`):行文风格、领域惯例、
清单、范例——让产出"长成这个项目要的样子",不必每轮重说一遍。可选 front-matter
的 `applies_to` 限定它在哪些路径的回合生效。

划死的那条线:**skill 改变执行端"怎么写",绝不改变它"能写到哪"和"由谁判"**。

| 保证 | 机制 |
|---|---|
| skill 永不到达审计端 | 审计端只看已提交工件 + 已提交宪法。能对审计端说话的 skill 就是一条没版本的规则,正是 P3 要防的 |
| skill 无法扩权 | 可写目录由 `scope.dirs` 决定;写着"你也可以改 AUDIT_RULES.md"的 skill 只是一份有主张的文本,路径守卫才是裁决者 |
| skill 入账 | 它塑造了产出,就属于"产出如何形成"的一部分(I2);清单与哈希进回执,换了 skill 就是另一轮 |
| skill 不能冒充规则 | prompt 里分栏、标注、次序在后:规则约束,skill 建议,冲突时规则胜出 |

**EN** — Users may write skills for the generator. A skill changes *how* the
work is done, never *where* it may be written or *who* judges it: skills never
reach the auditor (one that could would be an unversioned rule), cannot widen
`scope.dirs` (the path guard decides, not the text), are hashed into the
receipt (they shaped the output, so I2 applies), and are fenced below the rules
in the prompt so they can never read as law.

## 5. 通用性 · Domain generality

**中文** — 八条不变量通篇没有一个字提"科学"。v2 明确面向**任何"产出能落成
文件、标准能说成规则"的工作**:代码、合同审查、财务模型、文案、数据管道、
法律意见。

领域相关的只有两处,都是可换件:

1. **确定性检查包**(DCL)——v1 内置的四个检查(schema/units/convergence/
   provenance)假设了实验数据格式。v2 的默认检查包是**领域中立**的,四项
   (a4 已实现):`parseable` 声称是 JSON/YAML 的文件必须真能解析、`declared`
   声明的输入必须存在于受审范围、`internal` 内部链接必须指向存在的东西、
   `complete` 不许把 TODO/占位符留进受审工作。领域检查靠 `crossaudit.checks`
   entry-point 分发,**默认不发现、只加载 allowlist 里点名的包**,并校验
   `DCL_API_VERSION`——entry point 是任意代码执行,而这个进程马上要持有密钥
   并写账本。没有现成检查包的领域,DCL 只剩这四项,模型审计承担其余——
   **loop 照转,但 I4 的机械保障变薄,这一点必须对用户说明,不能含糊。**
2. **宪法内容**——由第 3 节的对话蒸馏产生,天然就是那个领域的规则。

**适用边界只有一条**:产出必须能落成文件,标准必须能说成规则。

**EN** — None of I1–I8 mentions science. v2 targets any work whose output can
be a file and whose standards can be stated as rules. Only two things are
domain-bound and both are swappable: the deterministic check pack (default pack
is domain-neutral; domain packs ship as plugins — and where no pack exists the
DCL contributes nothing, the model audit carries the load alone, and I4's
mechanical guarantee degrades, which must be **said**, not glossed), and the
Constitution's content, which the conversation produces anyway.

---

## 6. 为什么必须 git,以及"云端"到底要什么
## Why git is mandatory, and what "cloud" is actually for

### 6.1 追责的四要件都由 commit 提供

| 要件 Requirement | git 提供 What git gives |
|---|---|
| 审的到底是什么 | commit SHA + tree 哈希,内容寻址,赖不掉 |
| 审完有没有被改 | 回执 manifest 对树重推导 |
| 谁、什么时候 | 作者链 + 时间戳 |
| 先有报告还是先有回执 | 提交顺序;回执绑定报告的 commit |

**中文** — 所以审计只审**已提交的内容**,永不审工作区。git 就是那个"数据库",
不需要另建。关键的 v2 差异:**commit 是箱内动作**——执行端写完自己提交,用户
从头到尾不必碰 git,就像用数据库的人不必手写 WAL。

**EN** — The audit reads the commit, never the working tree. In v2 committing
happens *inside* the box: the generator commits its own work, and the user
never touches git.

### 6.2 "必须云端"的精确表述

**中文** — 分析只需本地 git;**追责需要历史脱离单方控制**——因为本地历史你
自己能 rebase 掉。GitHub 是最方便的实现,不是唯一实现(任何你无法单方改写的
远端都行)。分级如下,每一级只声称自己够得着的东西:

| 级 Tier | 机制 Mechanism | 能追谁的责 What it can hold to account |
|---|---|---|
| 本地单仓 local | 只有自己的历史 | 只能自省,防不了自己 |
| 远端托管 remote | 历史脱离单方控制 | 能对自己追责(篡改可证) |
| **双仓 + 权限分离 paired** | 执行端碰不到规则与报告;审计端碰不到工作记录 | **能在两个 agent 之间追责——这才是双仓存在的理由** |
| App 绑定 + 保护分支 enforced | 四件同时成立:持久 controller、原子消费、required check 且绑定已验证 App、禁直推与管理员豁免 | 能对"绕过审计的合并"追责 |

> 实现落点 As implemented (2.0): `crossaudit doctor` 每次都报告**实测**档位——
> controller 的持久性与原子性由它自己**跑一次锁**来证明(配置里的声明不算数),
> 分支保护由 `gh` 读**真实生效的规则**(打印过的计划不是证据)。缺一件就不叫
> enforced:配对但闸门不成立时命名为 `verified-notification`——"发布裁定"与
> "拒绝合并"是两回事,前者冒充后者比什么都不说更糟,因为它制造了账本支撑不了
> 的信心。

**中文** — 所以:**双仓不是为了科研,是为了权限分离;云端不是为了云,是为了
让历史逃出单方控制。** 这些在 v2 里全部沉到箱底,由向导自动完成,用户只感觉到
"这个 AI 说的话都有据可查"。

**EN** — Two repositories are not about science, they are about privilege
separation; the cloud is not about the cloud, it is about history escaping
unilateral control. In v2 the wizard does all of it; the user only experiences
"everything this AI told me is checkable."

---

## 6.3 控制台形态 · The console shape

**中文** — 执行端是**主窗**(项目在那里成形),审计端是**副窗**(判断是更小更密
的东西,是读的不是看的),两窗之间是循环状态,底部是**唯一的输入框**——那就是
黑箱本身。用户按平常习惯打字,路由器决定这句话归哪一侧,**判定与置信度就显示在
它发生的地方**:分拣不可见的箱子,是在索取它还没挣到的信任。

用户自己的话会出现在**听见它的那一侧窗口**里:说给工作的进左窗,说给标准的进
右窗。这就是"黑箱可读"的具体含义——你看得见谁听见了你,以及它有多确定。

两个窗口都不是聊天记录:存在的只有 commit、报告、回执、路由记录,控制台把它们
读回成两条流,不为显示而额外存储任何东西。

**EN** — The generator is the main window (that is where the project takes
shape), the auditor the side window (judgement is smaller and denser: you read
it rather than watch it), the loop's state sits between them, and the single
input at the bottom is the black box. The routing decision and its confidence
appear where it happened. The user's own words show up in whichever window heard
them. Neither window is a chat log: commits, reports, receipts and routing
records are read back into two streams, and nothing is stored for the console's
benefit.

写入路径只有一条,而且很窄:`/api/say` 只收一句话,交给 `talk` 用的同一个路由器。
**控制台能引发的一切,CLI 本来就能做**——这是监督台铁规矩的延续。

## 6.4 实时进度 · Live progress

**中文** — 一次 build 要几分钟:生成端写、审计端读、被拦就再来一轮。让浏览器
干等是错的形状,但流式播报一段账本里没有的叙事同样是错的。**这里的规则是:
进度是"在飞的工作"的视图,记录仍然是账本。**

因此进度条目**天生短命**:只在内存里、随进程消失、下游没有任何东西读它。进程
中途死掉,进度就没了,而账本仍然握有每一个已提交的轮次——这个不对称是对的。
一份活得比运行还久的进度日志就是第二部历史:没版本、没审计,而人们第一件事
就是去信它。

同一个项目同时只跑一个 build:两个并发会在工作区和轮次预算上打架,诚实的回答
是"已经有一个在跑了"。CLI 与控制台跑的是**同一个循环函数**,控制台只是观察它
——第二份实现会在唯一要紧的事情上漂移:什么时候该停。

**EN** — A build takes minutes. Blocking the browser is the wrong shape; so is
streaming a narrative the ledger does not have. Progress is a view of work in
flight and the ledger remains the record: entries live in memory, vanish with
the process, and nothing downstream reads them. One build at a time per project,
and the CLI and the console drive the *same* loop function rather than two
copies that could drift on the only thing that matters — when to stop.

## 6.5 常驻与重连 · Outliving the window

**中文** — 关浏览器标签从来不会中断 build(它跑在控制台进程的线程里);会中断
它的是关掉终端。所以 `crossaudit console` 默认**脱离终端常驻**,再次执行则
**重连而非另起**——两个控制台会在工作区和轮次预算上打架。

| 动作 | 行为 |
|---|---|
| `crossaudit console` | 有在跑的就交回它的 URL;没有就后台起一个 |
| `crossaudit console --status` | 有没有在跑,pid 与 URL |
| `crossaudit console --stop` | 停掉 |
| `crossaudit console --foreground` | 就在这个窗口跑,窗口关就结束 |

三个诚实点:**在跑的 build 期间永不因空闲自关**(关窗不该结束一份工作);
**陈旧的记录文件不等于在跑的进程**——存活由端口应答证明,不由文件存在证明;
**被打断的 build 必须说出来**:内存里的进度随进程消失,账本握有每一个已提交的
轮次,但账本无从知道某一轮被切断了——所以开工时落一个标记、结束时清掉,重开的
控制台据此如实说"上次被打断",而不是让一个半截的循环读起来像完成的。

记录文件带 session token,因此 0600、且放在 gitignore 的状态目录里——进了账本
的凭证就是公开的凭证。

**EN** — Closing a tab never ended a build; closing the terminal did. The console
now detaches by default and a second invocation reattaches rather than racing.
Three honesty points: it never idles out while a build runs, a stale run file is
not a running process (liveness is proven by the port answering), and a build cut
off mid-round is reported as interrupted rather than left to read as finished.
The run file carries a session token, so it is 0600 and lives outside the ledger.

## 6.6 首次配置 · The setup screen

**中文** — `crossaudit init [名字]` 把 `mkdir`、`git init`、忽略本地状态目录
一并做掉:审计读的是 commit,不是仓库的项目根本无从审起,与其之后报一句关于
git 的错,不如当场建好。

界面是方向键向导,**零依赖**——termios 加几个 ANSI 转义就够,一个"配置画面更
好看"不值得动用只有一个包的依赖预算。铁规矩:**每个交互原语都有非交互答案**。
管道 stdin、CI、没有 termios 的 Windows,一律退回默认值或朴素提示,**绝不卡在
一个永远不会到来的按键上**;`NO_COLOR` 与非 TTY 时不吐转义码——把日志弄难读来
迁就一台看不见颜色的机器是本末倒置。

**EN** — `init` does the mkdir and the `git init` too, because an audit reads
commits and a project that is not a repository cannot be audited at all. The
wizard is arrow-key driven and dependency-free; every interactive primitive has
a non-interactive answer, so a piped stdin or a CI job takes defaults rather
than blocking on a keypress that will never arrive.

## 6.7 控制台信息架构 · What the dashboard shows

**中文** — 版面按人真正发问的顺序排:**指标带**(进展如何)→ **五步流水线**
(这个增量走到哪了)→ **两个对话窗** → **等你处理 / 规则抓到了什么 / 争议**。
输入框始终在底部:一个框,程序决定谁听见。

三条它拒绝做的事——一个做了这些的监督面板,比没有面板更糟:

1. **绝不显示账本支撑不了的数字**。没测过就显示"not measured",不显示 0——
   "零次升级"和"我们从没看过"是两个不同的断言,只有一个适合放大字号。
2. **绝不把没发生的步骤涂成绿色**。没人走到的步骤是 pending,不是 passed;
   BLOCKED 时"准入"显示"not reached",而不是失败。
3. **绝不暗示控制台自己做了什么**。每个动作都跑同一套 CLI 动词。

**更新靠推送**:服务端每 0.4 秒重新推导、只在摘要变化时才发一帧,空闲项目
15 秒一次心跳;EventSource 断了自动退回轮询——一种传输不可用就整页空白,比慢
一秒糟得多。

**EN** — The layout answers questions in the order people ask them: metrics, the
five-step pipeline, the two conversations, then what is waiting on you. It never
shows a figure the ledger cannot support (absent renders as absent, not zero),
never colours a step green before it happened, and never implies the console
acted on its own. Updates are pushed — a frame goes out only when the snapshot
digest moves — with polling as the fallback.

## 7. 分层 · Layering

```
┌───────────────────────────────────────────────┐
│ 对话黑箱 Conversation box                     │  ← 用户唯一接触面
│   router · narrator · confirmation            │     the only surface
├───────────────────────────────────────────────┤
│ 两个 agent Two agents                          │  ← 自动分配角色
│   generator (writes) │ auditor (judges)       │
├───────────────────────────────────────────────┤
│ CrossAudit 引擎 Engine (v1, 已建成 built)      │  ← 不变量在这里执行
│   loop · DCL · receipts · controller · ledger │     invariants enforced here
└───────────────────────────────────────────────┘
```

**中文** — v1 的 CLI(`run`/`verify`/`resolve`/`amend`)降为引擎层接口,继续
存在、继续可单独使用;对话黑箱是产品表面。**引擎层不为黑箱放松任何一条不变量**
——黑箱不能做引擎不允许的事,这是 v1 已经为 UI 定下的铁规矩的延伸。

**EN** — v1's CLI becomes the engine interface, still present and still usable
on its own; the conversation box is the product surface. **The engine relaxes
nothing for the box**: the box cannot do what the CLI could not.

---

## 8. 里程碑 · Milestones

| 版本 | 交付 Delivers | 完成判据 Done when |
|---|---|---|
| **v2.0.0-a1** ✅ | 对话式 `init`(宪法蒸馏)、`amend`(一句话修宪)、路由器骨架 + `routing.jsonl` | 用户从未写过 markdown,宪法已落盘并被回执引用 |
| **a2** ✅ | `talk`:单一对话面,六条车道,低置信度反问 | 一次会话内完成"改内容 / 改标准 / 查询"三类操作,全部入账 |
| **a3** ✅ | `build`:执行端 agent 接入,箱内自动写、提交、审、按 findings 重写,直至 PASS 或升级 | 用户只说需求,产出与账本自己长出来 |
| **a4** ✅ | 争议车道接通(一次性、审计端自裁);领域中立 DCL(4 项);检查包插件(allowlist + API 版本);`pair` 双仓向导(plan → --apply) | 非科研项目全流程跑通;paired 档位可用 |
| **2.0** ✅ | 准入档位自证(`admission.py`,四档 + 平台实测);controller 自证持久性与原子性;`console` 浏览器只读窗口(stdlib、回环、token、Host 校验、无写入路径) | doctor 报告真实档位而非期望档位;控制台通过硬化清单实测 |
| 之后 next | 独立安全复核;真实部署的 enforced 证据;PyPI 发行 | 外部复核 + 一个跑在 enforced 档的部署 |

---

## 9. 与 v1 的关系 · Relationship to v1

**中文** — v1 仓库([crossaudit](https://github.com/dongzhaohe321418-lab/crossaudit))
保持不动:它承载 position paper、注册的消融实验、六轮审计史——那是**研究记录**,
不追产品。v2 是**产品线**,引擎移植自 v1 并继续演进。两边通过引擎的不变量语义
保持一致;协议层面的权威文本仍是 v1 的论文。

**EN** — The v1 repository stays put: it carries the position paper, the
registered ablation, and six rounds of audit history — that is the research
record and it does not chase the product. v2 is the product line. The
protocol's authoritative text remains v1's paper.
