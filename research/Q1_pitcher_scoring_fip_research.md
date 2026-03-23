# Q1 Research — Pitcher Impact Scoring: FIP vs ERA/WHIP

**Date:** March 2026
**Status:** Implemented — committed in `07d9a50`
**Files changed:** `engine/pitcher_impact.py`, `config/settings.py`, `models/pitcher.py`, `data/pitcher_client.py`, `db/schema.py`, `db/raw_store.py`

---

## Question

The original pitcher impact formula used ERA (0.30) and WHIP (0.25) as primary weights alongside K/9 and BB/9. Are ERA and WHIP the best available metrics for predicting pitcher performance? Should we use FIP instead?

---

## Research Findings

### ERA and WHIP are defense-contaminated

ERA (Earned Run Average) measures runs allowed per 9 innings. It includes hits-in-play (balls in the field of play where the outcome depends heavily on fielder positioning, range, and luck). A pitcher with a bad defense behind him will have an inflated ERA that does not reflect his true skill level.

WHIP (Walks + Hits per Inning Pitched) shares the same flaw — the "H" component includes all hits, including those driven by poor defense on balls in play (BABIP noise).

**FanGraphs (2024):** FIP is a demonstrably better predictor of a pitcher's **next-season ERA** than their current-season ERA itself.

**Research consensus:** ERA and WHIP are descriptive (what happened) not predictive (what will happen). For a betting model that must predict future game outcomes, we want predictive metrics.

---

### FIP — Fielding Independent Pitching

FIP isolates only the outcomes the pitcher fully controls:
- **Home runs** (HR) — pitcher decides what pitches to throw; HR rate reflects pitch quality
- **Walks** (BB) — pitcher's command
- **Hit batsmen** (HBP) — pitcher's command
- **Strikeouts** (K) — pitcher's stuff and command

Formula:
```
FIP = ((13 × HR) + (3 × (BB + HBP)) - (2 × K)) / IP + FIP_constant
```

The FIP constant (3.17, 5-year average 2020-2024 from FanGraphs GUTS table) re-centers FIP onto the ERA scale, making the numbers directly comparable to ERA values.

**FIP constant history (FanGraphs GUTS):**
| Year | Constant |
|------|----------|
| 2020 | 3.191 |
| 2021 | 3.173 |
| 2022 | 3.180 |
| 2023 | 3.152 |
| 2024 | 3.118 |
| 5-yr avg | 3.163 → rounded to **3.17** |

---

### xFIP — Extended FIP

xFIP replaces actual HR with expected HR based on fly ball rate (assuming a league-average HR/FB ratio). This removes park factor noise and BABIP luck from HR rate.

**However, xFIP is not implementable from the MLB Stats API alone.** The API returns `airOuts` (fly ball outs, excluding HR) but not total fly balls. The correct formula requires `fly balls = airOuts + homeRuns` as an approximation, which introduces its own imprecision.

**Decision:** Use FIP (exact calculation from available counts), not xFIP (approximate). FIP is still substantially better than ERA/WHIP for prediction.

---

### K/9 and BB/9 as standalone metrics

FanGraphs research confirms K/9 and BB/9 carry **additional predictive value beyond FIP** because they directly measure the two most skill-consistent outcomes:
- Strikeout rate is the most year-to-year stable pitcher metric
- Walk rate is the second most stable pitcher metric

These should be kept as separate weighted components alongside FIP.

---

### HR/9

HR rate is partly real skill (fly ball tendency, pitch mix) and partly park factor and luck (HR/FB variance). It is less stable year-to-year than K/9 or BB/9.

**Decision:** Include HR/9 at low weight (0.10) — real signal but noisy.

**League average HR/9 (Baseball-Reference 2024):**
```
5,453 HR / 43,116 IP × 9 = 1.137 ≈ 1.14
```
Using 1.15 for the 5-year rolling average to avoid over-fitting to a single season.

---

### MLB Stats API — Available Fields (Confirmed Live)

Tested against Gerrit Cole (player ID 543037) at `statsapi.mlb.com/api/v1/people/543037/stats?stats=season&group=pitching`:

**Available:**
- `homeRuns` ✓
- `baseOnBalls` ✓
- `hitBatsmen` ✓
- `strikeOuts` ✓
- `homeRunsPer9` ✓ (direct from API — used for HR/9 display)
- `strikeoutsPer9Inn` ✓
- `walksPer9Inn` ✓
- `inningsPitched` ✓
- `era`, `whip` ✓ (kept for display only)

**NOT Available:**
- `fip` — must calculate ourselves ✗
- `xfip` — requires fly ball count not available ✗
- `groundBalls`, `flyBalls` (total, including HR) — only `airOuts` (fly ball outs) available ✗

FIP is calculated in `pitcher_client.py::_extract_stat_line()` from the raw counting stats above.

---

## Final Formula (Implemented)

```python
# Weights (sum = 1.0)
fip_weight:         0.40   # primary — best predictor of future ERA
k9_weight:          0.25   # most durable, stable pitcher skill
bb9_weight:         0.20   # walk control — highly year-to-year consistent
hr9_weight:         0.10   # HR tendency — real but noisy
recent_form_weight: 0.05   # last-3-starts ERA — small form signal only

# League averages (MLB 2020-2024 rolling)
league_avg_fip:  4.20
league_avg_k9:   8.80
league_avg_bb9:  3.10
league_avg_hr9:  1.15

# FIP constant
fip_constant: 3.17
```

**ERA and WHIP:** Stored in DB and displayed on the model page for reference. **Not used in scoring.**

**Minimum IP for FIP:** 5.0 innings — below this, FIP is too noisy (small sample).

---

## Weight Rationale vs Old Formula

| Metric | Old Weight | New Weight | Reason |
|--------|-----------|-----------|--------|
| ERA    | 0.30      | 0.00      | Defense-contaminated; removed |
| WHIP   | 0.25      | 0.00      | Defense-contaminated; removed |
| FIP    | —         | 0.40      | Best fielding-independent predictor |
| K/9    | 0.20      | 0.25      | Increased — most stable skill signal |
| BB/9   | 0.15      | 0.20      | Increased — high year-to-year consistency |
| HR/9   | —         | 0.10      | New — real but noisy component |
| recent_ERA | 0.10 | 0.05   | Reduced — small sample form signal |

---

## Impact on the Model

- **Spring training (March 2026):** All pitchers score 50 (neutral) because MLB Stats API returns empty 2026 stats until the regular season. No change in model output during spring training.
- **Regular season:** Meaningful differentiation between elite starters (e.g. FIP 2.50, K/9 12.0) and poor starters (FIP 5.50, K/9 6.0), shifting probability by up to ±10 percentage points per game.
- **Probability shift formula:** `edge = away_score - home_score; prob_shift = (edge / 50) × 5.0` (max ±10pp)

---

## Sources

- FanGraphs Glossary — FIP: https://library.fangraphs.com/pitching/fip/
- FanGraphs GUTS table (FIP constants): https://www.fangraphs.com/guts.aspx?type=cn
- FanGraphs — "What FIP Tells Us About Pitchers" (2024)
- Baseball-Reference 2024 MLB Season Totals (HR/9 calculation)
- "ERA vs FIP as future performance predictors" — multiple FanGraphs research articles confirm FIP > ERA for next-season prediction
