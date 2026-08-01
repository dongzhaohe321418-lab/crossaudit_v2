# CrossAudit（中文）

> English: **[README.md](README.md)**

**一个对话面,两个互相制衡的 agent,一本可回放的账。**
**One conversation, two adversarial agents, one replayable ledger.**

你用平常的话说需求。程序把每句话分拣给执行端、审计端或账本;两个来自**不同厂商**
的模型互相盯着干活;整条监督史落进 git——出了问题能追到是谁、什么时候、按哪一版
规则。

You speak plainly. The program routes each sentence to the generator, the
auditor, or the ledger; two models from **different vendors** keep each other
honest; and the whole supervision history lands in git, so when something goes
wrong you can say who, when, and under which version of the rules.

```bash
pip install "crossaudit @ git+https://github.com/dongzhaohe321418-lab/crossaudit_v2@main"
crossaudit init my-project
cd my-project && crossaudit console
```

---

## 目录 · Contents

- [这是什么](#这是什么--what-this-is)
- [一、装它](#一装它--install)
- [二、建项目](#二建项目--set-up)
- [三、用它](#三用它--use-it)
- [四、浏览器控制台](#四浏览器控制台--the-console)
- [五、定制](#五定制--customise)
- [六、双仓与准入档位](#六双仓与准入档位--repositories-and-tiers)
- [命令速查](#命令速查--command-reference)
- [排错](#排错--troubleshooting)
- [卸载](#卸载--uninstall)
- [设计与协议](#设计与协议--design-and-protocol)

---

## 这是什么 · What this is

一个 AI 写东西,另一个**来自不同厂商**的 AI 按你定的规则审它,审不过就打回重写,
每一轮都落成 git commit。你只面对一个对话框。

| | |
|---|---|
| **适用范围** | 任何"**产出能落成文件、标准能说成规则**"的工作:综述、代码、合同审查、财务模型、文案、数据管道 |
| **你需要** | Python 3.10+、git、**两个不同厂商**的 API key |
| **你不需要** | 写规则文件、学 git、懂什么叫"增量"或"回执" |

八条不变量里没有一个字提"科学"。领域相关的只有确定性检查包(可插拔)和规则内容
(由你的话生成)。**没有现成检查包的领域,确定性层只剩通用四项、模型审计承担其余
——程序会明说,不含糊。**

---

## 一、装它 · Install

```bash
pip install "crossaudit @ git+https://github.com/dongzhaohe321418-lab/crossaudit_v2@main"
```

装完**什么也不会发生**——不联网、不认证、不写任何文件。这是刻意的:一个审计工具在
安装瞬间就伸手连网,会葬送它存在的理由。所有交互都在 `init` 之后。

Installing does nothing: no network, no auth, no writes. Everything interactive
lives behind `init`.

验证:

```bash
crossaudit --version     # crossaudit 2.6.0 (receipt schema 2)
```

<details>
<summary><b>想先隔离试用?</b></summary>

```bash
python3 -m venv ~/crossaudit-try && source ~/crossaudit-try/bin/activate
export CROSSAUDIT_KEYS_FILE=~/crossaudit-try/keys.env   # 密钥也关进来
pip install "crossaudit @ git+https://github.com/dongzhaohe321418-lab/crossaudit_v2@main"
```

删掉 `~/crossaudit-try` 即无痕。程序默认只往目录外写一处——`~/.crossaudit-keys.env`
——上面那行把它改道进沙箱。

</details>

**依赖只有 PyYAML 一个。** 模型接入用标准库的 `urllib`,没有任何厂商 SDK——一个
审计工具的可信,建立在小到可以通读之上。

---

## 二、建项目 · Set up

```bash
crossaudit init my-project
```

**建目录、`git init`、忽略本地状态目录,它一并做掉**——审计读的是 commit,不是仓库
的项目根本无从审起。已经有目录就直接在里面 `crossaudit init`。

向导问四件事,方向键选择:

```
╭──────────────────────────────────────────────────────────────╮
│ CrossAudit — setting up a supervised project                 │
╰──────────────────────────────────────────────────────────────╯
  ✓ created my-project
  ✓ git init — the ledger is git, and an audit reads commits

  [1/4] Who audits
  ↑↓ to move · enter to choose
  ❯ anthropic  Claude
    openai     GPT
    google     Gemini
```

| 问 | 说明 |
|---|---|
| **1. 谁审计** | 选厂商与模型 |
| **2. 谁生成** | **必须和审计端不同**,选一样会被当场拒绝——那是同源监督,正是本协议要防的 |
| **3. 两个 key** | 隐藏输入,写进 `~/.crossaudit-keys.env`(权限 600),**永不进仓库** |
| **4. 项目是什么、最怕出什么错** | 你说人话,系统蒸馏成编号规则,**展示给你看,点头才落盘** |

第四问是关键:

```
  your project, in a sentence or three
  ❯ 光伏产业综述。所有数字必须能追到文献来源,正文和数据表不许打架。

  ┌─ Drafted rules
  │ CA-SRC-001  [BLOCKER]  Every figure is sourced
  │     Each numeric claim names a source in the declared inputs.
  │     from you: "所有数字必须能追到文献来源"
  │ CA-TXT-001  [BLOCKER]  Prose matches data
  └─
  Commit these as the project's rules? [Y/n]
```

**你从头到尾没写过一行 markdown**,但规则存在、版本化、能被回执引用。每条规则都
带着**你自己的原话片段**,翻译对不对你自己能核。

> 管道输入、CI、没有 termios 的环境下,向导自动走默认值,**绝不卡在一个永远不会
> 到来的按键上**。

配置完成后:

```bash
source ~/.crossaudit-keys.env
crossaudit doctor
```

`doctor` 逐项体检,最后告诉你**真实的准入档位**——不是你希望的,是实测的。

---

## 三、用它 · Use it

### 主线:说一句话,循环自己转

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

执行端写、审计端判、findings 打回去重写,直到通过或交给你(默认最多三轮)。
**每轮都是 commit,每次裁定都有报告和回执。**

### 其余时候:对着一个黑箱说话

```bash
crossaudit talk "以后严查每个数字的来源"        # → 改标准,起草修宪,确认后提交
crossaudit talk "第三节太啰嗦了,压缩一下"       # → 改内容,交给执行端
crossaudit talk "现在怎么样了"                  # → 只读查询
crossaudit talk "那条拦错了,0.052 是引用原文"    # → 争议,回审计端重读一次
```

程序自己判断这句话属于哪条车道。**拿不准就问,绝不猜**——猜错方向会污染规则书或
产出。

<details>
<summary><b>六条车道分别做什么</b></summary>

| 车道 | 触发 | 落成什么 |
|---|---|---|
| `project` | 描述项目是什么 | 任务书 + 规则底稿 |
| `generator` | 「太长了」「补一节」「重写」 | 执行端开工,新增量 commit |
| `amendment` | 「以后严查…」「这条太严」 | 规则修订草案 → 确认 → **下一周期**生效 |
| `dispute` | 「那次拦错了」 | 按规则 ID **一次性**申辩,审计端重读自裁 |
| `resolve` | 「算了就这样吧」 | 人类对升级的裁决 |
| `query` | 「现在怎么样了」 | 只读,不产生任何变更 |

</details>

---

## 四、浏览器控制台 · The console

```bash
crossaudit console
```

打开是一块**一眼能读懂的面板**:

```
┌ Audits 12 ┬ Passed 8 75% ┬ Blocked 3 ┬ Waiting on you 1 ┬ Admitted 6 ┐
├─ The loop ────────────────────────────────────────────────────────────┤
│ ✓ Commit  →  ✓ Checks  →  ✓ Audit  →  ✕ Verdict  →  · Admission      │
├─ Generator (the work) ──────┬─ Auditor (the judgement) ──────────────┤
│ …                           │ …                                      │
├─ Waiting on you ─┬─ What the rules caught ─┬─ Disputes ──────────────┤
└─ [ Say what you want — the box decides who hears it… ]      [ Send ] ─┘
```

- **数据实时推送** —— 服务端只在状态真变了才发一帧,右上角有连接灯;断线自动退回轮询
- **build 进度逐步可见** —— 写了哪些文件、拦在哪条规则、第几轮、多少秒
- **关掉窗口 build 照跑**,再执行 `crossaudit console` 重连回同一个 URL

```bash
crossaudit console --status   # 在跑吗、pid、URL
crossaudit console --stop     # 停掉
```

<details>
<summary><b>安全措施(开端口这件事必须认真)</b></summary>

| 措施 | 挡住什么 |
|---|---|
| 只绑 `127.0.0.1` | 局域网访问 |
| 每个请求要 token,**完全不用 cookie** | CSRF——没有浏览器自动附带的凭证可供利用 |
| 校验 `Host` 必须是 localhost | DNS rebinding |
| 严格 CSP,全部内联 | 外部脚本注入与数据外泄 |
| **唯一写入路径是那个输入框** | 其他 POST 一律 404 |
| 密钥只报"有/无",永不渲染 | 密钥经浏览器泄漏 |
| 空闲自关(**但 build 跑着时永不自关**) | 忘关的端口 / 关窗掐掉工作 |

每一条都有一个会失败的测试守着。

</details>

**面板不会骗你的三条**:没测过就显示 "not measured" 而不是 0;没人走到的步骤是
pending 而不是 passed;每个动作都跑同一套 CLI 动词,窗口自己不写任何东西。

---

## 五、定制 · Customise

### 给执行端写 skill

```bash
crossaudit skills --new house-style   # 生成模板
crossaudit skills                     # 看当前生效的
```

编辑 `skills/house-style.md`——行文风格、领域惯例、范例、完成前的检查步骤。
front-matter 里 `applies_to: work/` 可限定生效范围。

**边界是硬的:skill 改变执行端*怎么写*,绝不改变它*能写到哪*、*由谁判*。**
审计端永远看不到 skill(能对审计端说话的 skill 就是一条没版本的规则);skill 写着
"你也可以改规则文件"也没用——**路径守卫才是裁决者**,那一轮会被当场打回。skill 的
哈希进回执,换了 skill 就是另一轮。

### 改规则

```bash
crossaudit amend "从现在起,每条主张都要注明来源版本"
```

起草 → 展示 → 确认 → 提交。**只在周期之间生效**:已在审的工作按它开始时的规则判,
不会被中途移动的标准判死。

---

## 六、双仓与准入档位 · Repositories and tiers

```bash
crossaudit pair               # 先看计划,不动你的账号
crossaudit pair --apply       # 真的建(需要 gh 已登录)
```

**双仓不是为了科研,是为了权限分离**:执行端碰不到规则和报告,账本因此能在**两个
agent 之间**追责。

`doctor` 报告的四个档位,全部**实测**而非配置声明:

| 档位 | 意味着 | 需要 |
|---|---|---|
| `local` | 只能自省——历史你自己能 rebase 掉 | 本地 git |
| `remote` | 能对自己追责——历史脱离单方控制 | 推到远端 |
| `paired` | 能在两个 agent 之间追责 | 双仓 + 权限分离 |
| `enforced` | **审计不过就拒绝合并** | 持久原子 controller + required check 绑定已验证 App + 禁直推与管理员豁免 |

差一件就诚实降级为 `verified-notification`——**"发布裁定"不等于"拒绝合并"**,让前者
冒充后者比什么都不说更糟,因为它制造了账本支撑不了的信心。

---

## 命令速查 · Command reference

| 命令 | 干什么 |
|---|---|
| `crossaudit init [名字]` | 建目录 + git init + 方向键向导 + 对话生成规则 |
| `crossaudit doctor` | 体检 + 真实准入档位;`--online` 探测 GitHub |
| `crossaudit build "…"` | 说一句话,循环自己写自己审 |
| `crossaudit talk "…"` | 对黑箱说话,自动分拣到六条车道 |
| `crossaudit console` | 浏览器面板,后台常驻;`--status` / `--stop` |
| `crossaudit amend "…"` | 改规则 |
| `crossaudit skills [--new 名]` | 执行端的外置技能 |
| `crossaudit check` | 只跑确定性检查层,不碰任何模型 |
| `crossaudit run` | 审计最新提交(build 的审计那一半) |
| `crossaudit verify <回执> [--admit]` | 逐项重新推导每个绑定;`--admit` 消费一次 |
| `crossaudit status` / `watch` / `routing` | 打开箱子:周期 / 往来 / 每次路由决定 |
| `crossaudit resolve <cycle> --reopen --because "…"` | 人类裁决升级(仅交互终端) |
| `crossaudit pair [--apply]` | 建双仓 |

**退出码是契约**,所有命令支持 `--json`:

| 码 | 含义 |
|---|---|
| `0` | 好结果(PASS / 已验证 / 已消费) |
| `10` | BLOCKED |
| `11` | 升级,或仅确定性层(DCL_ONLY) |
| `20` | 配置或环境拒绝 |
| `21` | 回执 / 完整性拒绝 |
| `22` | 网络或 provider 失败 |

<details>
<summary><b>环境变量</b></summary>

| 变量 | 用途 |
|---|---|
| `CROSSAUDIT_AUDITOR_KEY` | 审计端密钥(必需) |
| `CROSSAUDIT_GENERATOR_KEY` | 执行端密钥(`build` 需要) |
| `CROSSAUDIT_GENERATOR_MODEL` | 执行端模型名(`build` 必需) |
| `CROSSAUDIT_GENERATOR_PROVIDER` | 执行端 provider(默认按厂商推断) |
| `CROSSAUDIT_GENERATOR_BASE_URL` | 执行端自定义 endpoint |
| `CROSSAUDIT_KEYS_FILE` | 改密钥文件位置(沙箱用) |
| `CROSSAUDIT_ALLOW_CUSTOM_ENDPOINT` | 允许非内置 origin——**会把密钥发去那里**,所以必须显式开 |

</details>

---

## 排错 · Troubleshooting

| 症状 | 原因与解法 |
|---|---|
| `DENIED (config): no crossaudit.yml found` | 不在项目里,或还没 `crossaudit init` |
| `I1 violated: auditor vendor 'x' equals generator vendor 'x'` | 两端同厂——这是**故意拒绝**,换一端的厂商 |
| 裁定是 `DCL_ONLY` | 没有模型审计过。检查 `$CROSSAUDIT_AUDITOR_KEY`,`doctor` 会指出来 |
| `endpoint … is not this provider's built-in origin` | 用了自定义 base_url,需显式 `--allow-custom-endpoint` |
| `install mode source/editable may verify but never admit` | 可验证但不可准入——它的代码能在自报摘要后被改。装 wheel 才能准入 |
| 控制台 403 | token 不对,或 `Host` 不是 localhost。用 `crossaudit console --status` 拿正确 URL |
| build 被打断 | 重开控制台会**如实告诉你**上次被打断;已提交的轮次一条不少,再说一次即可继续 |

`crossaudit doctor` 是第一站——它逐条指出缺什么、怎么补。

---

## 卸载 · Uninstall

```bash
pip uninstall crossaudit
```

程序只往项目外写两处:`~/.crossaudit-keys.env`(密钥)和 pip 缓存。项目内的
`.crossaudit/`(本地状态)和 `cycles/`(账本)随项目走——**账本是记录,删之前想
清楚**。

---

## 设计与协议 · Design and protocol

- **[DESIGN.md](DESIGN.md)** —— 核心设计,中英对照:三条柱子、路由器、通用性边界、
  为什么必须 git、控制台信息架构、里程碑
- **[v1 仓库](https://github.com/dongzhaohe321418-lab/crossaudit)** —— 协议本身、
  position paper、注册的消融实验、六轮审计史(研究记录,不追产品)

三条贯穿全局的原则:

1. **审计只审已提交的内容。** 追责的四要件(审的是什么、审后有没有被改、谁和何时、
   报告与回执孰先孰后)全由 commit 提供。v2 里 commit 是箱内动作,你不必碰 git。
2. **对话是入口,账本是形态。** 你说的话经确认变成有版本、有 commit 哈希的规则;
   审计永远按落盘的那一版执行。
3. **箱子是交互上的黑箱,不是记录上的黑箱。** 每次路由决定、每轮修订、每条拦截都
   入账。你**不必**打开看,但**随时能**打开看。

---

## 状态 · Status

`2.6.0`,187 个测试。已落地:对话式规则蒸馏、六车道路由器、`build` 闭环、一次性
争议、领域中立检查包、检查包插件、双仓向导、准入档位自证、实时推送的浏览器面板、
后台常驻与重连。未落地:enforced 档的实地证据、PyPI 发行。

## 许可 · License

[MIT](LICENSE) © 2026 Zhaohe Dong, Yuhao Chen
