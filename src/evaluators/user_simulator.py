"""模拟用户 - 用 LLM 扮演被叫方，自动生成完整多轮对话"""

from ..llm_client import DeepSeekClient


USER_SIMULATOR_PROMPT = """你正在扮演一个接到外呼电话的普通人。请根据场景设定自然回应。

【你的身份】{user_persona}

【你的行为倾向】{behavior}

【规则】
1. 像真人接电话一样说话，简短口语化
2. 每次回复1-2句话，不超过30字
3. 根据行为倾向自然反应，不要刻意配合也不要刻意刁难
4. 可以提问、犹豫、打断、跑题，像真人一样
5. 只输出你说的话，不要任何标注或解释"""


class UserSimulator:
    def __init__(self, llm: DeepSeekClient = None, persona: str = "", behavior: str = ""):
        self.llm = llm or DeepSeekClient()
        self.persona = persona
        self.behavior = behavior
        self.system_prompt = USER_SIMULATOR_PROMPT.format(
            user_persona=persona,
            behavior=behavior,
        )
        self.history: list[dict] = []

    def respond(self, agent_message: str) -> str:
        """根据客服的话生成用户回复。
        从模拟用户LLM的视角：客服说的是user消息，自己回复是assistant。
        """
        self.history.append({"role": "user", "content": agent_message})

        messages = [
            {"role": "system", "content": self.system_prompt},
            *self.history,
        ]

        reply = self.llm.chat(messages, max_tokens=512, temperature=0.8)
        self.history.append({"role": "assistant", "content": reply})
        return reply


# 预定义的用户画像场景
RIDER_SCENARIOS = [
    {
        "name": "配合型骑手",
        "persona": "你是一个美团外卖骑手，刚报名了飞毛腿",
        "behavior": "你愿意配送，态度积极，简单确认后就准备开工",
    },
    {
        "name": "犹豫型骑手",
        "persona": "你是一个美团外卖骑手，报了飞毛腿但有点后悔",
        "behavior": "你有点犹豫，担心完不成单量，会问一些问题，但最终可能被说服",
    },
    {
        "name": "拒绝型骑手",
        "persona": "你是一个美团外卖骑手，家里临时有事",
        "behavior": "你今天确实跑不了，家里有急事。第一次会委婉说不行，被挽留后会坚持拒绝",
    },
    {
        "name": "提问型骑手",
        "persona": "你是一个美团外卖骑手，对飞毛腿规则不太清楚",
        "behavior": "你会连续问几个问题：怎么退出、奖励多少、排名怎么算。问完后表示可以跑",
    },
    {
        "name": "跑题型骑手",
        "persona": "你是一个美团外卖骑手",
        "behavior": "你会问一些超出范围的问题，比如今天天气、能不能换区域、站长能不能帮忙调单",
    },
]

COURSE_SCENARIOS = [
    {
        "name": "配合型机构负责人",
        "persona": "你是一个培训机构的校长，用这个平台发课",
        "behavior": "你比较配合，听完说明后会确认操作方式",
    },
    {
        "name": "忙碌型负责人",
        "persona": "你是一个培训机构的负责人，正在忙",
        "behavior": "你一开始说很忙，但对方说1分钟后你愿意听。会简短回应",
    },
    {
        "name": "开车型负责人",
        "persona": "你是一个培训机构的负责人，正在开车",
        "behavior": "你接起电话后说正在开车，希望对方稍后再打",
    },
    {
        "name": "多疑问型负责人",
        "persona": "你是一个培训机构的负责人，对技术不太懂",
        "behavior": "你会反复问区别、价格、怎么操作，需要对方耐心解释",
    },
]
