# -*- coding: utf-8 -*-
"""生成吞吐基准语料（固定内容，可复现）：

  20 个扫描风格 PDF（页面渲染成图片再嵌入，走视觉链路，3/5 页交替）
  20 个电子 PDF（原生文字层，2-4 页）
  10 个图片（JPG）
  10 个纯文本（.txt）

用法：python make_bench_corpus.py --out <dir>
内容为合成中文文档，含姓名/电话/身份证/地址/日期/金额等 PII，
按索引确定性变化（不依赖随机数，跑几遍都一致）。
"""

import argparse
import io
import os

import fitz

SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许"
GIVEN = "伟芳娜敏静丽强磊军洋勇艳杰娟涛明超霞平刚桂英"


def person_name(i: int) -> str:
    return SURNAMES[i % len(SURNAMES)] + GIVEN[(i * 7) % len(GIVEN)] + GIVEN[(i * 13 + 5) % len(GIVEN)]


def phone(i: int) -> str:
    return f"1{3 + i % 6}{(i * 137) % 10}{(10000000 + i * 991137) % 100000000:08d}"


def id_card(i: int) -> str:
    return f"{110101 + i % 90}{1960 + i % 45}{1 + i % 12:02d}{1 + i % 28:02d}{(i * 37) % 10000:04d}"


def doc_lines(i: int) -> list[str]:
    name, name2 = person_name(i), person_name(i + 101)
    return [
        f"业务往来确认函（编号：HT-2026-{1000 + i:04d}）",
        "",
        f"甲方联系人：{name}，联系电话：{phone(i)}，身份证号：{id_card(i)}。",
        f"甲方地址：北京市朝阳区建国路{18 + i % 80}号院{1 + i % 9}号楼{101 + i % 30}室。",
        f"乙方经办人：{name2}，电子邮箱：user{i:04d}@example-corp.cn，电话：{phone(i + 55)}。",
        f"乙方单位：华宸信息技术（北京）有限公司第{1 + i % 12}分公司。",
        f"签约日期：2026年{1 + i % 12:02d}月{1 + i % 28:02d}日，合同金额：人民币{(i % 90 + 10) * 1.37:.2f}万元。",
        f"银行账号：6222 0210 {1000 + i % 9000:04d} {2000 + (i * 3) % 8000:04d}，开户行：中国工商银行北京分行。",
        "",
        "本函涉及的个人信息仅用于双方业务核对，请妥善保管，不得外传。",
        f"经办备注：{name}于2026-0{1 + i % 9}-15完成初审，{name2}复核通过。",
        f"月度服务费：{8 + i % 22}K-{15 + i % 30}K/月，服务期十二个月。",
    ]


def build_text_page(doc: fitz.Document, i: int) -> None:
    page = doc.new_page(width=595, height=842)
    y = 72.0
    for line_no, line in enumerate(doc_lines(i)):
        size = 16 if line_no == 0 else 11
        page.insert_text((56, y), line, fontname="china-s", fontsize=size)
        y += size * 2.0


def digital_pdf(path: str, i: int, pages: int) -> None:
    doc = fitz.open()
    for p in range(pages):
        build_text_page(doc, i * 10 + p)
    doc.save(path)
    doc.close()


def page_image_bytes(i: int, dpi: int = 130) -> bytes:
    doc = fitz.open()
    build_text_page(doc, i)
    pix = doc[0].get_pixmap(dpi=dpi)
    data = pix.tobytes("jpg")
    doc.close()
    return data


def scanned_pdf(path: str, i: int, pages: int) -> None:
    doc = fitz.open()
    for p in range(pages):
        img = page_image_bytes(i * 10 + p)
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=img)
    doc.save(path)
    doc.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    for i in range(20):
        scanned_pdf(os.path.join(args.out, f"scan_{i:02d}.pdf"), i, 3 if i % 2 == 0 else 5)
    for i in range(20):
        digital_pdf(os.path.join(args.out, f"digital_{i:02d}.pdf"), 100 + i, 2 + i % 3)
    for i in range(10):
        with open(os.path.join(args.out, f"image_{i:02d}.jpg"), "wb") as f:
            f.write(page_image_bytes(200 + i))
    for i in range(10):
        body = "\n".join("\n".join(doc_lines(300 + i * 3 + k)) for k in range(3))
        with io.open(os.path.join(args.out, f"text_{i:02d}.txt"), "w", encoding="utf-8") as f:
            f.write(body)

    total = len(os.listdir(args.out))
    size = sum(os.path.getsize(os.path.join(args.out, p)) for p in os.listdir(args.out))
    print(f"corpus ready: {total} files, {size / 1e6:.1f} MB at {args.out}")


if __name__ == "__main__":
    main()
