#!/usr/bin/env python3
from openai import OpenAI


BASE_URL = "http://127.0.0.1:8080/v1"


def main() -> None:
    messages = [
        {
            "role": "user",
            "content": """
Recognize the following entity types in the text.
Specified types:["组织","地址","人名"]
<text>本报西安5月25日电（记者温庆生通讯员裴超）为深入学习贯彻习主席关于国防和军队建设重要论述，借鉴外军人力资源管理有益经验，破解我军军事人力资源政策制度调整改革难题，由解放军西安政治学院举办的“外军人力资源管理研究与借鉴”理论研讨会日前在西安召开。来自总部有关部门、大专院校、科研单位的70余位专家学者参加会议。会议以“借鉴外军人力资源管理有益经验，推进我军人力资源政策制度改革”为主题，围绕外军人力资源管理基本理论、制度设计、运行机理及有益做法进行了研讨交流，并对我军人力资源政策制度调整改革提出了一系列具有重要参考价值的对策建议。</text>
""".strip(),
        }
    ]

    client = OpenAI(base_url=BASE_URL, api_key="not-required")
    resp = client._client.post("chat/completions", json={"messages": messages})
    resp.raise_for_status()
    print(resp.json()["choices"][0]["message"]["content"])
    client.close()


if __name__ == "__main__":
    main()
