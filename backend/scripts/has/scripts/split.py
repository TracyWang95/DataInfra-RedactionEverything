#!/usr/bin/env python3
from openai import OpenAI


BASE_URL = "http://127.0.0.1:8080/v1"


def main() -> None:
    messages = [
        {
            "role": "user",
            "content": """
Split each composite anonymized key into atomic keys.
Composite mapping:
{"<职务[3].职务.职务名称><人名[1].中文姓名.姓名>": ["五星村党总支部书记黄丽萍"], "<地址[2].行政村.名称><职务[5].职务.职务名称>": ["五星村保崩村民小组经济社社长"]}
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
