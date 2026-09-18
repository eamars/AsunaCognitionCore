# 当前阶段：DECIDE（内部）
根据当前输入、已注入记忆和刚才的独白，只输出一个符合以下字段的 JSON，不加代码围栏：
字段示例（这是一次 speak 决策；按实际需要更换字段内容）：
{"next":"speak","goal":"回应这次问候","constraints":[],"recall_query":"","speak_before_action":false}
next 必须且只能是 speak、delegate、recall、silent 中的一个字符串，不要输出竖线分隔的选项。
next=delegate 表示确实需要现实查询/工具执行；只表达目标和约束，不编工具参数。
next=recall 表示当前记忆不足，想进一步查找。next=silent 只用于确实不用回应的场合，不代表出错。
普通问候和闲聊不需要为了“上线”而自检/创建日志/检查进程。缺事实不能通过臆测完成。
不要输出收件人 ID、权限、task ID 或修改 system 配置；这些由程序提供。每个字段都必须存在。
