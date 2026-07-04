# E2E Harness锛堟湁澶?Chrome锛屾案涓嶆棤澶达級

浜斿眰闂搁棬鐨勭 3 灞傘€傜洰鏍囩敱 `E2E_BASE_URL` 鍐冲畾锛堥粯璁?`http://localhost:8000`锛屽嵆闅ч亾鍒?5090 鎴栨湰鍦板叏鏍堬級銆?
## 鍒嗗眰

| Tier | 鑴氭湰 | GPU | 浣曟椂璺?|
|---|---|---|---|
| 1 鍐掔儫 | `smoke_routes.py`锛堝叏璺敱娓叉煋锛夈€乣perm_matrix.py`锛堟潈闄愮煩闃碉細API 403 + UI 闂ㄧ锛?| 鏃?| 姣忚疆蹇呰窇锛岄殢鏃跺彲鎵撶敓浜ч毀閬?|
| 2 榛勯噾璺緞 | `golden_single.py`锛堝崟鏂囦欢鏂囨湰鍏ㄩ摼璺細涓婁紶鈫掕瘑鍒啋鍖垮悕鍖栤啋鎴愬搧鏍忔棤鍘熷PII锛屸渽宸插疄鐜帮級 | 杞?| 閮ㄧ讲鍚?/ 闅忔椂锛堟枃鏈矾寰勭绾э級 |
| 2 寰呭疄鐜?| `golden_batch.py`锛堟壒閲忎簲姝ュ惈鎵归噺纭锛夈€乣golden_structured.py`锛堝鍏モ啋绛栫暐鈫掍氦浠橈級銆乣golden_export.py`锛堝紓姝ュ垎鍗峰鍑猴級 | 鏈?| 涓嬩竴杞?loop |

## 杩愯

```bash
cd e2e
python smoke_routes.py          # Tier 1
python perm_matrix.py
# 鎴?cd frontend && npm run e2e 锛? Tier 1 鍏ㄩ儴锛?```

璐﹀彿锛歚E2E_USERNAME`/`E2E_PASSWORD`锛堥粯璁?e2e_user锛岄璺戣嚜鍔ㄦ敞鍐岋紝鏅€氳鑹诧級銆?绠＄悊鍛樹晶鏂█闇€瑕?`E2E_ADMIN_USERNAME`/`E2E_ADMIN_PASSWORD`锛堜笉鍏ュ簱锛岃窇鍓?export锛夈€?
## 绾﹀畾

- 閫夋嫨鍣ㄤ紭鍏?`data-testid`锛涙柊鍔熻兘钀藉湴鏃跺悓姝ヨˉ testid銆?- 姣忎釜鑴氭湰涓€涓満鏅嚱鏁帮紝`common.run()` 璐熻矗璧锋祻瑙堝櫒/鐧诲綍/缁撴灉妯箙锛坄E2E_PASS xxx`锛夈€?- 澶辫触=鎶?AssertionError锛岄€€鍑虹爜闈?0锛孋I 鍙洿鎺ユ帴銆?