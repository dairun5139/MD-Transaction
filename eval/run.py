"""
MD Transaction RAG — 评测脚本

用法：
    python eval/run.py                # 对全部问题跑一遍评测
    python eval/run.py --rebuild      # 先重建索引再评测

输出：
    - 逐题结果（PASS / FAIL / WARN）
    - 分类汇总统计
    - 总分
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# 将项目根目录加入 sys.path
PROJ_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJ_ROOT))

import rag_app


EVAL_FILE = Path(__file__).parent / "questions.jsonl"


def load_questions() -> list:
    questions = []
    with EVAL_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


def evaluate_one(vectorstore, q: dict) -> dict:
    """对一条问题进行评测，返回结果 dict。"""
    question = q["question"]
    must_contain = q.get("must_contain", [])
    must_not = q.get("must_not", [])
    expect_refuse = q.get("expect_refuse", False)

    start = time.time()
    result = rag_app.ask(vectorstore, question)
    elapsed = time.time() - start

    answer = result["answer"]
    sources = result["sources"]

    # 检查是否拒答
    refused = "未检索到足够依据" in answer or "依据不足" in answer

    # 检查必须包含的关键词
    missing = [kw for kw in must_contain if kw not in answer]
    # 检查禁止出现的关键词
    forbidden = [kw for kw in must_not if kw in answer]

    # 判定
    if expect_refuse:
        passed = refused
        status = "PASS" if passed else "FAIL"
        reason = "应拒答" if not passed else "正确拒答"
    elif missing:
        status = "FAIL"
        passed = False
        reason = f"缺关键词: {missing}"
    elif forbidden:
        status = "WARN"
        passed = False
        reason = f"禁词出现: {forbidden}"
    else:
        status = "PASS"
        passed = True
        reason = "OK"

    return {
        "id": q["id"],
        "category": q.get("category", ""),
        "risk": q.get("risk", "low"),
        "question": question[:60],
        "status": status,
        "passed": passed,
        "reason": reason,
        "refused": refused,
        "elapsed": round(elapsed, 2),
        "sources_count": len(sources),
        "answer_len": len(answer),
    }


def main():
    rebuild = "--rebuild" in sys.argv

    print("=" * 64)
    print("  MD Transaction RAG — 评测")
    print("=" * 64)
    print()

    # 加载向量库（必要时重建）
    if rebuild:
        print("[*] 重建索引...")
        docs = rag_app.load_documents(rag_app.DATA_DIR)
        if not docs:
            print("ERROR: no documents found")
            return
        docs = rag_app.clean_documents(docs)
        docs = rag_app.filter_documents(docs)
        docs = rag_app.mask_documents(docs, config=rag_app.MASK_CONFIG)
        chunks = rag_app.split_documents(docs)
        vs = rag_app.build_vectorstore(chunks)
        print("  索引重建完成。\n")
    else:
        vs = rag_app.load_vectorstore()
        if vs is None:
            print("ERROR: 索引不存在，请先运行 rag_app.py 或加 --rebuild 重建。")
            return
        print("  使用已有索引。\n")

    questions = load_questions()
    print(f"  共 {len(questions)} 道测试题\n")

    # 逐题评测
    results = []
    for q in questions:
        r = evaluate_one(vs, q)
        results.append(r)
        icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(r["status"], "?")
        print(f"  {icon} [{r['id']}] {r['status']:4s} | {r['elapsed']:5.1f}s | {r['question'][:50]}...")
        if r["reason"] != "OK":
            print(f"         理由: {r['reason']}")

    # 汇总
    print()
    print("=" * 64)
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    avg_time = sum(r["elapsed"] for r in results) / max(total, 1)
    avg_sources = sum(r["sources_count"] for r in results) / max(total, 1)

    print(f"  总分: {passed}/{total}  ({passed / max(total, 1) * 100:.0f}%)")
    print(f"  平均耗时: {avg_time:.1f}s")
    print(f"  平均来源数: {avg_sources:.1f}")
    print()

    # 按分类统计
    by_cat = {}
    for r in results:
        cat = r["category"]
        by_cat.setdefault(cat, {"total": 0, "passed": 0})
        by_cat[cat]["total"] += 1
        if r["passed"]:
            by_cat[cat]["passed"] += 1

    print("  分类通过率:")
    for cat in sorted(by_cat):
        stats = by_cat[cat]
        pct = stats["passed"] / max(stats["total"], 1) * 100
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        print(f"    {cat:10s}  {bar}  {stats['passed']}/{stats['total']}  ({pct:.0f}%)")

    # 按风险统计
    by_risk = {}
    for r in results:
        risk = r["risk"]
        by_risk.setdefault(risk, {"total": 0, "passed": 0})
        by_risk[risk]["total"] += 1
        if r["passed"]:
            by_risk[risk]["passed"] += 1

    print()
    print("  按风险级别:")
    for risk in ("high", "medium", "low"):
        if risk in by_risk:
            stats = by_risk[risk]
            pct = stats["passed"] / max(stats["total"], 1) * 100
            print(f"    {risk:6s}  {stats['passed']}/{stats['total']}  ({pct:.0f}%)")

    print("=" * 64)

    if failed:
        print(f"\n  ⚠️ {failed} 题未通过，建议优先排查 FAIL 项。")
    else:
        print("\n  ✅ 全部通过！")


if __name__ == "__main__":
    main()
