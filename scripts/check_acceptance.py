import json, sys
from pathlib import Path
from collections import Counter

def ok(cond): return "PASS" if cond else "FAIL"

def main():
    print("=" * 60)
    print("ACCEPTANCE CRITERIA CHECK")
    print("=" * 60)

    final = Path("data/final")
    train = list(open(final/"train.jsonl", encoding="utf-8"))
    val   = list(open(final/"val.jsonl",   encoding="utf-8"))
    test  = list(open(final/"test.jsonl",  encoding="utf-8"))
    print(f"\n[1] train={len(train)}  val={len(val)}  test={len(test)}")
    print(f"    {ok(len(train)>=7000)} (need >= 7000)")

    scored = [json.loads(l) for l in open("data/candidates/scored.jsonl", encoding="utf-8")]
    total  = len(scored)

    # [2] Order distribution
    order_counts = Counter(",".join(r["plan"].get("order",[])) for r in scored)
    max_share = max(c/total for c in order_counts.values()) if scored else 0
    print(f"\n[2] Max order share: {max_share:.1%}")
    print(f"    {ok(max_share<=0.25)} (need <= 25%)")
    for order, cnt in order_counts.most_common(5):
        print(f"      {cnt/total:5.1%}  {order or '(empty)'}")

    # [3] Real sources
    fmts = [json.loads(l) for l in open(final/"formatted.jsonl", encoding="utf-8")]
    real = sum(1 for f in fmts if f.get("metadata", {}).get("source") == "real")
    real_share = real / max(len(fmts),1)
    print(f"\n[3] Real source share: {real_share:.1%} ({real}/{len(fmts)})")
    print(f"    {ok(real_share>=0.30)} (need >= 30%)")

    # [4] Score stats
    scores = sorted(r["metrics"]["score"] for r in scored)
    p75 = scores[int(len(scores)*0.75)]
    smax = max(scores)
    savg = sum(scores)/len(scores)
    print(f"\n[4] Score: avg={savg:.3f}  p75={p75:.3f}  max={smax:.3f}")
    print(f"    p75  {ok(p75>0.50)} (need > 0.50)")
    print(f"    max  {ok(smax>0.70)} (need > 0.70)")

    # [5] Failure rate
    validated = [json.loads(l) for l in open("data/candidates/validated.jsonl", encoding="utf-8")]
    fail = sum(1 for v in validated if not v.get("tests_passed"))
    fail_rate = fail / max(len(validated),1)
    print(f"\n[5] Failure rate: {fail_rate:.1%} ({fail}/{len(validated)})")
    print(f"    {ok(fail_rate<0.10)} (need < 10%)")
    reasons = Counter(v.get("reason") for v in validated if not v.get("tests_passed"))
    for r, c in reasons.most_common():
        print(f"      {c:6d}  {r}")

    # [6] Split overlap
    train_ids = {json.loads(l)["id"] for l in open(final/"train.jsonl", encoding="utf-8")}
    val_ids   = {json.loads(l)["id"] for l in open(final/"val.jsonl",   encoding="utf-8")}
    test_ids  = {json.loads(l)["id"] for l in open(final/"test.jsonl", encoding="utf-8")}
    overlap   = (train_ids & val_ids) | (train_ids & test_ids) | (val_ids & test_ids)
    print(f"\n[6] Split overlap: {len(overlap)} ids")
    print(f"    {ok(not overlap)}")

    # [7] Intensity distribution
    intensities = Counter(r["plan"].get("intensity","?") for r in scored)
    ti = sum(intensities.values())
    print(f"\n[7] Intensity distribution:")
    for k,v in sorted(intensities.items()):
        print(f"      {k:8s}: {v/ti:.1%} ({v})")
    light = intensities.get("light",0)/max(ti,1)
    print(f"    light  {ok(light>=0.15)} (need >= 15%, got {light:.1%})")

    # [8] Unique orders
    print(f"\n[8] Unique orders: {len(order_counts)}")

    print("\n" + "=" * 60)

main()
