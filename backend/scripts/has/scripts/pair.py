#!/usr/bin/env python3
from openai import OpenAI


BASE_URL = "http://127.0.0.1:8080/v1"


def main() -> None:
    messages = [
        {
            "role": "user",
            "content": """
<original>请帮我提升一下整体表述。


1989年10月27日上午莫斯科时间九点，苏联在哈萨克共和国的萨雷奥泽克试验场销毁了它拥有的九百五十七枚中短程导弹中的最后一批导弹。苏军第一副总参谋长奥梅利切夫上将对塔斯社记者宣布上述消息时说，27日销毁的最后一枚中短程导弹是西方所称的ss·23导弹，射程五百公里，是八十年代初部署的。 关注更多精彩：香港财富俱乐部（微信公号：hkfortuneclub） 业务合作，请直接留言（请留下联络方式及微信号）</original>
<anonymized>请帮我提升一下整体表述。


<日期/时间[1].绝对时间.完整表达>，苏联在哈萨克共和国的萨雷奥泽克试验场销毁了它拥有的<数字[1].数量.完整表达>中短程导弹中的最后一批导弹。<人名[1].军方职务.完整称谓>对塔斯社记者宣布上述消息时说，<日期/时间[1].日期.日>销毁的最后一枚中短程导弹是西方所称的<导弹型号[1].型号.完整名称>，射程<数字[2].距离.完整表达>，是<日期/时间[2].年代.时期>部署的。 关注更多精彩：香港财富俱乐部（微信公号：<微信公号[1].账号.用户名>） 业务合作，请直接留言（请留下联络方式及微信号）</anonymized>
Extract the mapping from anonymized entities to original entities.
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
