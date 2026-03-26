#!/usr/bin/env python3
from openai import OpenAI


BASE_URL = "http://127.0.0.1:8080/v1"


def main() -> None:
    messages = [
        {
            "role": "user",
            "content": """
Recognize the following entity types in the text.
Specified types:["人名","联系方式","职务","密码","组织","地址","文件","账号"]
<text>（原标题：山东菏泽单县村民自建房屋坍塌已致4人遇难） 单县一在建民房发生坍塌事故 菏泽市政府副市长王忠想看望伤员齐鲁网10月25日菏泽讯24日下午16时许，单县谢集镇白寨行政村一村民在自建房屋时，突然发生坍塌事故，致12人不同程度受伤。事发后，当地有关部门和周边群众一起迅速展开救援，并将伤者及时送往附近医院救治。截至24日23时，4人经抢救无效死亡，1人伤势较重正在全力救治中，其余7人伤情较轻，正在医院观察治疗。当地警方已介入调查事故原因，善后工作正在进行。

提取人名、组织、时间、地点，以 JSON 返回</text>
""".strip(),
        },
        {
            "role": "assistant",
            "content": '{"人名":["王忠想"],"联系方式":[],"职务":["菏泽市政府副市长"],"密码":[],"组织":["菏泽市政府","齐鲁网"],"地址":["单县谢集镇白寨行政村"],"文件":[],"账号":[]}',
        },
        {
            "role": "user",
            "content": "Replace the above-mentioned entity types in the text.",
        },
    ]

    client = OpenAI(base_url=BASE_URL, api_key="not-required")
    resp = client._client.post("chat/completions", json={"messages": messages})
    resp.raise_for_status()
    print(resp.json()["choices"][0]["message"]["content"])
    client.close()


if __name__ == "__main__":
    main()
