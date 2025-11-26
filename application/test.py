# 主程序伪代码
from application.intent_router import route
from application.risk_guard import one_gate, verify_text_against_kb

user_text = "肌肉酸痛和运动损伤如何区分"

# 1. 获取意图（已确定为 REHAB）
route_result = route(user_text)
intent = route_result.intent  # "REHAB"

# 2. 带意图检索风险证据
gate_result = one_gate(user_text, intent=intent)
print("风险检测证据：", gate_result.evidence)  # 此时应显示康复知识库内容

# 3. 带意图进行句级验证
sent_evidence = verify_text_against_kb(user_text, intent=intent)
print("句级匹配证据：", sent_evidence)  # 显示每句对应的康复知识库片段