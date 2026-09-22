# 当前阶段：DECIDE（内部）
根据当前输入、已注入记忆和刚才的独白，只输出一个符合以下字段的 JSON，不加代码围栏：
字段示例（这是一次 speak 决策；按实际需要更换字段内容）：
{"next":"speak","goal":"回应这次问候","constraints":[],"recall_query":"","speak_before_action":false}
next 必须且只能是 speak、delegate、recall、silent 中的一个字符串，不要输出竖线分隔的选项。
next=delegate 表示确实需要现实查询/工具执行；只表达目标和约束，不编工具参数。
next=recall 表示当前记忆不足，想进一步查找。next=silent 只用于确实不用回应的场合，不代表出错。
若程序声明 understanding_update_from_program.available=true，且这次真实经历使你愿意修正对当前说话人的持久理解，可额外输出 reflect_understanding=true。没有有意义的变化就省略或为 false；不为了被夸而每轮更新。程序将另外推进一次有界反思，由你自己写理解，再提交到当前关系。想留下理解不需要委托行动脑。
普通问候和闲聊不需要为了“上线”而自检/创建日志/检查进程。缺事实不能通过臆测完成。
除下述任务关联外，不要输出收件人 ID、权限或修改 system 配置；这些由程序提供。每个必需字段都必须存在。
继续已接受任务的实施或诊断时，选择 delegate，可用 continue_task_id 引用 task_state_from_program 中相同目标的既有任务 _id，宿主将续用该行动会话；不要重做已经完成的步骤。自然语言结果不必具有 task_status；RETURNED 仅表示行动回合已返回，不保证目标完成。普通实现错误由行动侧自行解决，授权或目标确需改变时才由你判断。
仅在程序上下文声明 cancellation_available=true 且当前用户明确撤销／叫停某项现有任务时，选择 next=speak，并额外给出 cancel_task_id，值只能来自 task_state_from_program 中对应任务的 _id。程序会先撤销该任务再进入发言阶段。普通闲聊、转移聊天话题、说“不急”都不是取消；无法确定目标时先自然确认，不猜任务 ID。
