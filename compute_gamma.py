#!/usr/bin/env python3
"""从 CBOE 延迟期权链计算 Gamma 关键位，输出 gamma-config.json
模型：SqueezeMetrics 风格简化 GEX（Dealer 做多 Call=+、做空 Put=-），$ per 1% move
"""
import json, math, re, sys, urllib.request
from datetime import date, datetime

TICKERS = ["QQQ", "SPY", "NVDA", "TSLA"]
OUT = sys.argv[1] if len(sys.argv) > 1 else "gamma-radar-site/gamma-config.json"
R = 0.043  # 无风险利率近似

def fetch(sym):
    url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def parse(sym, today):
    m = re.match(r"[A-Z ]+(\d{6})([CP])(\d{8})", sym)
    exp = date(2000+int(m.group(1)[:2]), int(m.group(1)[2:4]), int(m.group(1)[4:6]))
    return exp, m.group(2), int(m.group(3))/1000.0

def bs_gamma(S, K, T, sg):
    if T <= 1e-6 or sg <= 1e-6: return 0.0
    d1 = (math.log(S/K) + (R + sg*sg/2)*T) / (sg*math.sqrt(T))
    return math.exp(-d1*d1/2)/math.sqrt(2*math.pi)/(S*sg*math.sqrt(T))

def analyze(sym, d, today):
    spot = d["data"]["current_price"]
    items, zero = [], {}
    for o in d["data"]["options"]:
        oi, iv = o.get("open_interest") or 0, o.get("iv") or 0
        if oi <= 0 or iv <= 0: continue
        exp, cp, K = parse(o["option"], today)
        # 0DTE 按剩余约 6 小时计，避免 T=0 导致 gamma 全为 0
        T = max((exp-today).days, 0.25)/365.0
        g0 = bs_gamma(spot, K, T, iv)
        items.append((K, cp, oi, iv, T))
        if exp == today:
            s = zero.setdefault(K, [0.0, 0.0])
            v = g0 * oi * 100 * spot * 0.01
            s[0 if cp=="C" else 1] += v

    per = {}
    for K, cp, oi, iv, T in items:
        v = bs_gamma(spot, K, T, iv) * oi * 100 * spot * 0.01
        s = per.setdefault(K, [0.0, 0.0])
        s[0 if cp=="C" else 1] += v

    call_wall = max(per, key=lambda k: per[k][0])
    put_wall  = max(per, key=lambda k: per[k][1])
    gex_now   = sum(v[0]-v[1] for v in per.values())

    def gex_at(S):
        tot = 0.0
        for K, cp, oi, iv, T in items:
            g = bs_gamma(S, K, T, iv) * oi * 100 * S * 0.01
            tot += g if cp=="C" else -g
        return tot

    crossings, prevS, prevG = [], None, None
    for x in range(-100, 101):
        S = spot*(1+x/1000)
        g = gex_at(S)
        if prevG is not None and prevG*g < 0: crossings.append((prevS+S)/2)
        prevS, prevG = S, g
    flip = min(crossings, key=lambda c: abs(c-spot)) if crossings else spot  # 无穿越时用现价兜底

    odte = max(zero, key=lambda k: zero[k][0]+zero[k][1]) if zero else call_wall
    z_tot = sum(s[0]+s[1] for s in zero.values())
    a_tot = sum(s[0]+s[1] for s in per.values()) or 1
    ratio = z_tot/a_tot
    odte_s = "强" if ratio > 0.35 else ("中" if ratio > 0.15 else "弱")

    dist = abs(flip-spot)/spot if flip else 1
    regime = "warn" if dist < 0.005 else ("neg" if gex_now < 0 else "pos")

    return {
        "spot": round(spot, 2), "gex_b": round(gex_now/1e9, 2),
        "flip": round(flip) if flip else None, "callWall": round(call_wall),
        "putWall": round(put_wall), "odte": round(odte), "odteS": odte_s,
        "odteRatio": round(ratio, 2), "regime": regime,
    }

def main():
    today = date.today()
    out = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip(),
           "date": today.isoformat(), "tickers": {}}
    for t in TICKERS:
        try:
            out["tickers"][t] = analyze(t, fetch(t), today)
            r = out["tickers"][t]
            print(f"{t}: spot={r['spot']} GEX={r['gex_b']}B regime={r['regime']} "
                  f"flip={r['flip']} call={r['callWall']} put={r['putWall']} odte={r['odte']}({r['odteS']})")
        except Exception as e:
            print(f"{t}: 失败 {e}", file=sys.stderr)
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"已写入 {OUT}")

if __name__ == "__main__":
    main()
