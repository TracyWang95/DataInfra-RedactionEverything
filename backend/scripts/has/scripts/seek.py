#!/usr/bin/env python3
from openai import OpenAI


BASE_URL = "http://127.0.0.1:8080/v1"


def main() -> None:
    messages = [
        {
            "role": "user",
            "content": """
The mapping from anonymized entities to original entities:
{"<组织[1].新闻机构.完整名称>":["新华社"],"<职务[1].新闻传媒.称谓>":["记者"],"<人名[1].个人.姓名>":["张毅荣"],"<组织[2].科研机构.完整名称>":["罗伯特·科赫研究所"],"<职务[2].政府职务.完整称谓>":["德国卫生部长"],"<人名[2].个人.姓名>":["劳特巴赫"],"<组织[3].政府机构.完整名称>":["联邦议院"],"<文件[1].法律法规.正式名称>":["《传染病防治法》","德国最新版《传染病防治法》"]}
Restore the original text based on the above mapping:
According to <组织[1].新闻机构.完整名称> in Berlin on March 24 (reported by <职务[1].新闻传媒.称谓> <人名[1].个人.姓名>), the latest pandemic data released on the 24th by Germany’s disease control agency <组织[2].科研机构.完整名称> showed that Germany reported 318,387 new confirmed COVID-19 cases compared to the previous day, marking the first time daily cases exceeded 300,000.

The data also indicated 300 new COVID-19 related deaths on the 24th, bringing the total death toll to 127,822. The 7-day infection rate set a new record as well, with 1,752 new confirmed cases per 100,000 people over seven days.

On the 24th, <职务[2].政府职务.完整称谓> <人名[2].个人.姓名> called on all federal states at <组织[3].政府机构.完整名称> to use the new <文件[1].法律法规.正式名称> to strengthen efforts to control the spread of the virus. He said, “We must unite to get through this severe wave of the pandemic.” The <文件[1].法律法规.正式名称> came into effect on the 20th, generally lifting most COVID-19 prevention measures.
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
