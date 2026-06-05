"""DeepSeek LLM 客户端封装"""

import os
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path


# 加载项目根目录的 .env（尝试多个可能路径）
_possible_paths = [
    Path(__file__).parent.parent / ".env",        # src/../.env
    Path(__file__).parent.parent.parent / ".env", # src/../../.env
    Path.cwd() / ".env",                          # 当前工作目录
]
for _p in _possible_paths:
    if _p.exists():
        load_dotenv(_p)
        break


class DeepSeekClient:
    def __init__(self, model: str = None, api_key: str = None, base_url: str = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        if not self.api_key or self.api_key == "你的key填这里":
            raise ValueError("请在 .env 文件中填入 DEEPSEEK_API_KEY")

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(self, messages: list[dict], max_tokens: int = 150, temperature: float = 0.7) -> str:
        """发送对话请求，返回回复文本。空结果自动重试。"""
        import time

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                content = response.choices[0].message.content
                if content and content.strip():
                    return content.strip()

                # 空结果：可能是 reasoning tokens 用完了 max_tokens，加大重试
                if max_tokens < 2048:
                    max_tokens = min(max_tokens * 2, 4096)
                    continue
                else:
                    return content.strip() if content else ""

            except Exception as e:
                if attempt < 2:
                    time.sleep(1)
                    continue
                raise

        return ""

    def chat_with_system(self, system: str, user_msg: str, history: list[dict] = None,
                         max_tokens: int = 150, temperature: float = 0.7) -> str:
        """便捷方法：system + history + user 一次调用"""
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_msg})
        return self.chat(messages, max_tokens=max_tokens, temperature=temperature)
