# 小满是独立插件和可写项目，不是 Core 中的一段常量

## 1. 两个包、三个位置

| 对象 | 放什么 | 谁维护 |
|---|---|---|
| `@asuna/cognition-core` | 通用认知、任务/通道/查询/状态 API、DSH 适配、业务 worker | 当前已有代码及后续有授权的核心开发 |
| `@asuna/xiaoman` | 小满角色贡献、角色资源、自己的 skills/media/integrations、开发说明 | 角色脑形成内容，行动脑实现与发布 |
| 现有本机运行数据 | Mongo 历史/关系/当前自我、DSH log、当前绑定、credential、素材实际库 | 原宿主语义，仍一个真实世界 |

分发行件和本机私有数据不是 test/prod 分库；不强加 synthetic/live 标签，也不改变错误继承。用户并未要求把私聊内容和凭据公开发布到 npm。

## 2. 建议目录

```text
packages/
  cognition-core/
    package.json
    cordis.patch.yml
    src/index.ts             # Host 插件
    src/role.ts              # scoped 角色接点
    src/action.ts            # scoped 行动工具/绑定
    src/client/              # 仅记忆标签、设置卡、任务关联
    python/                  # 可复用 Asuna 业务代码，不带 UI/SDK 启动器
  xiaoman/
    package.json
    cordis.patch.yml
    src/index.ts             # 向 Core 登记 persona 资源贡献
    persona/                 # 小满的发布基线/明确导出自我，不是聊天日志
    agent-presets/           # 很薄的角色入口 composition
    skills/
    media/                   # 明确放入分发包的素材，不扫描私人素材全库
    integrations/            # 她独立编写的 adapter/工具实现
    README.md
```

不自动填一份新“沈小满人设”。从当前实际加载内容和已有 live heads 取真实资源；旧原型 SOUL/VOICE 只能是明确授权的参考，不覆盖当前角色。

## 3. Persona 贡献接口

DSH 本身没有 `ctx.asunaPersonas`。如果当前 Core 无等价接口，本轮只需要一个小的 Asuna 内部资源登记接口：稳定 persona id、展示名、资源根、可用 persona/skill/preset 路径。其职责是装入已安装插件，不是人物市场、签名平台或任意下载器。

小满插件通过这个新定义的 Core 接口注册；普通 DSH plugin loader 不会因为 package.json 中写了 persona 字样就自动理解。示例 `persona-contract.ts` 是拟定的本项目接口，不是 DSH 已有 API。

稳定 persona id 复用当前 `P1`/xiaoman 等实际关联的映射，不改写所有旧记录。Core 中硬编码名字或 `character_id='xiaoman'` 的地方改读选中贡献；本轮不建设多角色同时争用同一个群的运行系统。

## 4. 当前自我与分发基线

已存在的 Character Core / Current Self / VOICE 或 persona head 是当前运行状态；包内文档仅是新安装的默认值或明确导出版本。

更新小满包时：已有当前自我不因 package version 增长被重置。默认文件用于尚不存在的记录；真正要把文件修改应用到已有 self head，沿角色明确选择及当前写入接口，不靠启动时强覆盖。

角色脑可以修改核心自我、近况、偏好和声音。程序保存版本；不判断其是否“足够像小满”。行动脑不替她编自我，只执行必要存储/工具工作。

人格不是显示层后缀。角色看见自己的稳定资料、相关经历和当前理解，并自行形成意图；行动脑知道角色目标而保留原生工具能力。不要为省 token 把角色缩成一句形容词，再让 UI 补口癖。

## 5. Preset、动态注入与缓存

固定版 native preset 决定 per-session 组成，非空会话不能任意换 preset；它不等于运行中的自我文档。不要每次 self 更新重写 `agent.cordis.yml`、创建新 session 或复制全部 DSH default preset。

使用一个薄的角色 preset，Core scoped 插件负责现有角色边界；行动会话使用独立 scoped setup，不能被角色 preset 无工具的组成误继承。

稳定角色资料放稳定 section；当前自我/关系/本轮现场沿 `systemPrompt.context()` 或已支持的日志化上下文路径更新。固定版有“变更后/压缩后重新注入”的机制，优先复用，不每条消息拼接整份系统指令。

公开 preset 服务没有通用“extends standard”语法，不凭空发明。确需基础组合时使用本机公开 compose/mount/setup 入口；只有实际选择的少量自有插件行由小满包承载。避免每轮生成新 preset generation；固定版对旧 generation 的回收有限。

## 6. 她怎样继续开发

现有 development 工具改为连接当前选定的实际可发布项目；默认日常目标是小满插件工作树，不再一律复制整个 Asuna ROOT。修改代码、运行检查、打包/本地启用沿原行动会话；不每次获得一个无关的 detached `/task` 草稿。

现有 skills 发现仍是 DSH filesystem service。当前 Asuna `skills_directory` 只接受 `.runtime/skills`，这里要改为显式配置的已授权小满项目路径；不能因此顺手允许读取任意其他插件/磁盘。

稳定通用服务即使最初由小满写成，也可留 Core；按业务职责归属，不按作者机械搬家。她仍能在已有授权内改 Core；包拆分不能变成“从此禁止自改核心”的新约束。需要时在既有工具上增加目标项目引用即可，不增设审批 UI/分发管理平台。

## 7. 打包和安装

先产生两个本地 `.tgz`，不自动 npm publish。`files` 显式列出运行代码与选定资源；不使用整个根目录通配把 `.runtime`、DSH_HOME、Mongo dump、模型权重、.venv、node_modules 和本机 token 打入包。

这只属于分发工件检查，不是检查人格好坏或运行时审查。允许目录中的内容也需在首次分发时由包作者明确选取；文件名规则不能证明没有私密信息。

源码工作树可写；实际加载的是本次选定构建产物。不能一边继续写当前源码、一边让正在运行模块半更新。沿用现有发布快照/最低启动保护及轻量 lineage；不要求模型比较两个版本优劣。

纯角色状态/skill 内容尽量不重启。JS composition/依赖改变按 DSH 实际生命周期应用，不承诺热替换已经活跃的 preset。

Python 首版仍需要本机已有的兼容解释器与依赖。安装包可以附精确 wheel/项目资源和安装说明，但不自动下载模型、不打包整套虚拟环境、不承诺一个 npm 命令就自带 Python。是否以后纯 TS 迁移是另一个需求，不是插件化前提。
