#!/usr/bin/env python3
from openai import OpenAI


BASE_URL = "http://127.0.0.1:8080/v1"


def main() -> None:
    messages = [
        {
            "role": "user",
            "content": """
Recognize the following entity types in the text.
Specified types:["作品","人名"]
<text>《梦想咨客》讲述的是一群怀揣着热情服务人群的中国年轻创业青年，为驴友介绍中国各地不同的民族风情和地理风貌。动画中主角们不同的性格碰撞，形成的一串串乌龙和笑料化为了创业路上的点点欢笑。每一集讲述的是一个以主角“胡妈”作为核心的乐骋旅行社遇到的疑难杂症，但奇思与努力让这些困难迎刃而解，以其特有的乐骋精神传播正能量。

麻烦把这段中文内容翻译成英文。</text>
""".strip(),
        },
        {
            "role": "assistant",
            "content": '{"作品":["《梦想咨客》"],"人名":["胡妈"]}',
        },
        {
            "role": "user",
            "content": """
Replace the above-mentioned entity types in the text according to the existing mapping pairs:{"<作品[1].动画作品.片名>":["《泉城水大碗茶》","【奇趣视界】"],"<作品[2].动画作品.片名>":["《梦想咨客》"],"<作品[3].动画作品.片名>":["穿越时空的对话"],"<作品[4].动画作品.片名>":["《宝岛一村》上剧场专属版"],"<人名[1].中文姓名.本名>":["胡妈"]}
""".strip(),
        },
    ]

    client = OpenAI(base_url=BASE_URL, api_key="not-required")
    resp = client._client.post("chat/completions", json={"messages": messages})
    resp.raise_for_status()
    print(resp.json()["choices"][0]["message"]["content"])
    client.close()


if __name__ == "__main__":
    main()
