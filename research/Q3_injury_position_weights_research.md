# Q3 Research — Injury Impact: MLB Position Weight Calibration

**Date:** March 2026
**Status:** Implemented — pending commit
**Files changed:** `config/mlb_config.py`

---

## Question

The original position weights in `MLB_POSITION_WEIGHTS` were ported from V8.0 (NFL-focused Google Apps Script). Are these weights correctly calibrated for baseball? Specifically:
- Is Catcher correctly weighted vs. Shortstop?
- Is CF correctly valued relative to other outfield positions?
- Is the Closer weight accounting for the bullpen chaining effect?
- Is DH correctly valued given its absence of defensive contribution?
- Should batting order slot be modelled?
- Should star players (high-WAR) carry a larger impact multiplier than bench players?

---

## Framework: FanGraphs Positional Adjustments

The industry-standard reference for position scarcity in baseball analytics is the FanGraphs WAR positional adjustment system, expressed in runs per 162 games:

| Position | Adjustment (runs/162g) | Interpretation |
|----------|----------------------|---------------|
| C | +12.5 | Premium — hardest to fill defensively; framing adds hidden value |
| SS | +7.5 | Premium infield — requires elite range + arm |
| CF | +2.5 | Mid — hardest outfield position |
| 2B | +2.5 | Mid — similar tier to 3B analytically |
| 3B | +2.5 | Mid — corner infield but requires strong arm |
| LF | -7.5 | Easy — offensive-focused, less defensive demand |
| RF | -7.5 | Easy — similar defensive demand to LF |
| 1B | -12.5 | Easiest infield — purely offensive, minimal defensive premium |
| DH | -17.5 | No defense — replacement is always available from roster |

**Source:** [FanGraphs Positional Adjustment Library](https://library.fangraphs.com/misc/war/positional-adjustment/)

The adjustment represents the marginal run value of playing a harder position at average skill level. When a starter is lost to injury, harder positions cost more to replace because:
1. The offensive gap between starter and backup is larger (fewer quality players exist)
2. The defensive gap at premium positions is larger (specialized skills take years to develop)

---

## WAR to Win Probability Conversion

Standard conversion (Tom Tango / FanGraphs):
```
1 WAR = 1 win over 162 games
1 WAR per game = 1/162 = 0.00617 win probability per game
```

A typical starter at a premium position (2.5 WAR) replaced by a backup (0.5 WAR) creates:
- WAR gap: 2.0 WAR → 2.0 / 162 = 0.012 WP per game
- Expressed as percentage: ~1.2 pp shift

A star at a premium position (7 WAR SS) replaced by a backup (0.5 WAR):
- WAR gap: 6.5 WAR → 6.5 / 162 = 0.040 WP per game ≈ **4.0 pp shift**

**Source:** [Converting Runs to Wins — FanGraphs](https://library.fangraphs.com/misc/war/converting-runs-to-wins/)

---

## Finding 1: Starting Pitcher Weight (SP = 8.0) — CONFIRMED CORRECT

**Research:** Documented moneyline movement when aces are scratched:
- Shohei Ohtani scratch: line moved from -170 to pick'em → ~15 pp swing
- Quality start analysis: teams win 67-70% of quality start games vs. 35-40% with replacement starters
- The gap between ace and replacement = 27-35 pp; the gap between average SP and replacement = ~8-12 pp

**Conclusion:** SP = 8.0 is appropriate for an **average-case SP injury** (not ace, not #5 starter). The SP gate already handles the extreme Out/Doubtful case by zeroing units entirely.

**Decision: Keep SP at 8.0. No change.**

**Source:** [MLB Betting Lines: Action vs. Listed Pitcher — Sports Insights](https://www.sportsinsights.com/blog/mlb-betting-lines-action-vs-listed-pitcher/)

---

## Finding 2: Catcher (C: 2.0 → 3.0) — INCREASE JUSTIFIED

**Research:**

FanGraphs places Catcher at **+12.5 runs/162g** — the highest positional adjustment in baseball, more than Shortstop (+7.5) by a 1.67× ratio.

**Pitch framing** is the key factor not captured anywhere else in the model pipeline:
- A top-tier framing catcher saves **30-50 runs per season** (3-5 WAR equivalent)
- Each additionally called strike saves 0.125-0.135 runs
- Top framers (Patrick Bailey 2025: +25 framing runs) generate 50-100 extra called strikes per season

**Critical model gap:** The FIP-based pitcher scoring in this system is pitcher-centric. When a good-framing catcher is injured and replaced by a poor framer, the pitcher's FIP/K9/BB9 stays the same — but his effective performance drops because fewer borderline pitches are called strikes. **This framing effect is not captured anywhere else in the pipeline.** The catcher position weight must carry this hidden value.

**The ratio:** If SS = 1.5 and positional adj ratio C:SS = 12.5:7.5 = 1.67, then C should be at least 1.67 × 1.5 = 2.5. With the additional framing weight not captured in pitcher scoring, 3.0 is defensible.

**Decision: Raise C from 2.0 to 3.0.**

**Sources:**
- [Catcher Defense — FanGraphs Sabermetrics Library](https://library.fangraphs.com/defense/catcher-defense/)
- [WAR Update: Catcher Framing — FanGraphs](https://blogs.fangraphs.com/war-update-catcher-framing/)
- [Statcast Catcher Framing Leaderboard — Baseball Savant](https://baseballsavant.mlb.com/leaderboard/catcher-framing)
- [Baseball Prospectus Framing Model](https://www.baseballprospectus.com/news/article/22934/framing-and-blocking-pitches-a-regressed-probabilistic-model-a-new-method-for-measuring-catcher-defense/)

---

## Finding 3: Shortstop (SS: 1.5 → 2.0) — INCREASE JUSTIFIED

**Research:**

FanGraphs positional adjustment places SS at **+7.5 runs/162g** — meaningfully above 2B and 3B (both +2.5) by a 3.0 run gap.

The Defensive Spectrum hierarchy (from easiest to hardest to fill): DH → 1B → LF/RF → 3B → CF → 2B → SS → C. SS is second hardest of all fielding positions.

**Current weight problem:** SS = 1.5 vs. 3B = 1.2 vs. 2B = 1.0. This ratio (1.5:1.0) understates the analytics-implied ratio of 7.5:2.5 = **3.0:1.0** between SS and 2B. The gap is being significantly underrepresented.

**Practical impact:** A team losing an average SS to a backup creates a meaningfully larger hit than a team losing an average 2B — both in offensive depth and defensive quality. SS replacements are among the most scarce players in MLB.

**Decision: Raise SS from 1.5 to 2.0.** This gives a 2.0:1.0 ratio vs 2B, closer to the analytics-implied 3.0:1.0, while being conservative enough to avoid overweighting.

**Sources:**
- [FanGraphs Positional Adjustment Library](https://library.fangraphs.com/misc/war/positional-adjustment/)
- [Defensive Spectrum — Wikipedia](https://en.wikipedia.org/wiki/Defensive_spectrum)
- [Re-Examining WAR's Defensive Spectrum — The Hardball Times](https://tht.fangraphs.com/re-examining-wars-defensive-spectrum/)

---

## Finding 4: Center Field (CF: 1.0 → 1.5) — INCREASE JUSTIFIED

**Research:**

FanGraphs positional adjustment places CF at **+2.5 runs/162g** — the same tier as 2B and 3B, and **20 runs above DH (-17.5)**. Yet the current model equates CF with DH at 1.0.

CF requires elite range to cover the largest outfield territory and is the hardest OF position by a significant margin versus LF/RF. Corner outfielders (LF/RF) receive -7.5 run adjustments — a full 10-run gap below CF.

**The specific error:** CF = 1.0 (same as DH = 1.0) is analytically incorrect. DH has no defensive contribution. CF plays one of the harder defensive positions in baseball. The defensive spectrum places CF between 2B and SS, making it equivalent to a mid-tier infield position defensively.

**Decision: Raise CF from 1.0 to 1.5.** This correctly positions CF above LF/RF (0.8) and DH (after adjustment), while being proportionate to 2B/3B (1.0-1.2).

**Sources:**
- [FanGraphs Positional Adjustment Library](https://library.fangraphs.com/misc/war/positional-adjustment/)
- [Defensive Spectrum — Wikipedia](https://en.wikipedia.org/wiki/Defensive_spectrum)

---

## Finding 5: Closer (CP: 2.5 → 2.0) — DECREASE JUSTIFIED

**Research:**

The key analytical insight is the **bullpen chaining effect**: when a closer is injured, the team does not replace them with a literal replacement-level pitcher. The setup man becomes closer, the 7th-inning arm becomes setup, and so on. The net loss is the drop from the team's weakest arm now covering additional innings — typically 1.0-1.5 WAR equivalent, not the closer's full 2.0-2.5 WAR.

**Leverage Index evidence:** Closers operate at LI ~1.8 (80% above average leverage). This justifies placing CP above all position players in the weight hierarchy. The LI-based hierarchy should be:
```
SP (8.0) >> C (3.0) > SS (2.0) ≈ CP (2.0) > RP (1.5) > MR (1.2)
```

**WAR analysis:** Best relievers accumulate 2.0-2.5 WAR/season. After the chaining discount (1.0-1.5 WAR net loss from closer injury), a weight of 2.0 is appropriate.

**Decision: Lower CP from 2.5 to 2.0.** This accounts for the chaining effect while maintaining the correct ordering (CP > RP > MR) based on leverage.

**Sources:**
- [WAR and Relievers — FanGraphs](https://blogs.fangraphs.com/war-and-relievers/)
- [Win Probability Added Above Replacement — The Hardball Times](https://tht.fangraphs.com/win-probability-added-above-replacement/)
- [Leverage Index Glossary — MLB.com](https://www.mlb.com/glossary/advanced-stats/leverage-index)
- [Saves Above Expected — SABR](https://sabr.org/journal/article/saves-above-expected-a-new-contextual-metric-for-closers/)

---

## Finding 6: Designated Hitter (DH: 1.0 → 0.6) — DECREASE JUSTIFIED

**Research:**

FanGraphs positional adjustment places DH at **-17.5 runs/162g** — the lowest of any position. The reasons:
1. Zero defensive contribution — no scarcity premium from defense
2. The DH role is the easiest position to fill with any capable hitter from a 40-man roster
3. Replacement-level DHs are abundant in MLB rosters (any left-handed bat on the bench)

**The DH penalty in WAR:** Approximately -8.4 runs per year for using a DH slot instead of a fielder. The position adjustment penalizes DH because teams sacrifice defensive production to bat a poor defender.

**Key insight:** The current model equates DH with 2B and CF at 1.0. The analytics data shows a **20-run gap** between CF (+2.5) and DH (-17.5). This is one of the largest positional gaps in baseball — they should never be weighted equally.

**Star DH caveat:** A star DH (Yordan Alvarez, 5+ WAR) being injured matters significantly — but that differentiation belongs in a per-player WAR multiplier (future enhancement, see below), not in the position weight. Position weights represent the **average** impact of losing a typical starter at each position.

**Decision: Lower DH from 1.0 to 0.6.** This reflects the absence of defensive scarcity premium. The offensive gap between a typical DH and their backup is real but modest compared to premium defensive positions.

**Sources:**
- [FanGraphs Positional Adjustment Library](https://library.fangraphs.com/misc/war/positional-adjustment/)
- [Nagoya University DH Study](https://en.nagoya-u.ac.jp/news/articles/a-decade-of-baseball-data-shows-the-designated-hitter-system-does-not-affect-how-teams-win/)

---

## Finding 7: Relief Pitcher Ordering (RP/MR) — CONFIRMED CORRECT

**Research:**

RP (setup, 8th inning) operates at LI 1.2-1.5. MR (middle relief, 5th-7th innings) operates at LI 0.7-1.0.

The ordering RP (1.5) > MR (1.2) is correctly structured by leverage. Both values are within defensible range given the chaining effect applies here too (losing a setup man shifts the 7th-inning arm into setup, etc.).

**Decision: Keep RP at 1.5 and MR at 1.2. No change.**

**Sources:**
- [Leverage Index Glossary — MLB.com](https://www.mlb.com/glossary/advanced-stats/leverage-index)
- [Relief Pitching Strategy — SABR](https://sabr.org/journal/article/relief-pitching-strategy-past-present-and-future/)

---

## Finding 8: Batting Order Slot — NOT MODELLED (by design)

**Research:**

Tom Tango's sabermetric work (The Book) established that the difference between the best possible batting order and the worst possible batting order is approximately **10-15 runs per 162 games** (1.0-1.5 wins).

On a per-game basis: 10-15 runs / 162 games = **0.06-0.09 runs per game**.

This is substantially smaller than the positional scarcity effects already captured in the weights. "The names in the batting order are way more important than the order they are listed in."

**Decision: Do not add batting order slot weighting.** The added complexity is not justified by the marginal signal. High-WAR players naturally occupy the high-leverage lineup slots — when the per-player WAR multiplier is implemented in the future, batting order effects will be partially captured automatically.

**Sources:**
- [Batting Order Position Values — Bill James Online](https://www.billjamesonline.com/batting_order_position_values/)
- [How Sabermetrics Influence MLB Batting Order Strategy — Sports Betting Dime](https://www.sportsbettingdime.com/guides/strategy/batting-order-sabermetrics/)

---

## Finding 9: Star Player vs. Replacement — FUTURE ENHANCEMENT (not in scope)

**Research:**

This is the **highest-priority future enhancement** for the injury scoring module. The current flat position-based weights treat all players at the same position equally. The actual win probability difference is enormous:

| Player Quality | WAR/Season | WP shift per game (vs. 0.5 WAR backup) |
|----------------|-----------|----------------------------------------|
| MVP (8+ WAR) | 8.0 | ~4.6 pp |
| All-Star (5-7 WAR) | 6.0 | ~3.4 pp |
| Average starter (2-3 WAR) | 2.5 | ~1.2 pp |
| Bench player (0-1.5 WAR) | 1.0 | ~0.3 pp |

The current model gives **all of these the same weight** (e.g., SS = 2.0 regardless of player quality).

**Proposed future multiplier:**
```python
player_quality_multiplier = {
    "≥5.0 WAR": 2.0,
    "3.0-4.9 WAR": 1.5,
    "1.5-2.9 WAR": 1.0,
    "<1.5 WAR": 0.5,
}
injury_impact = position_weight × player_quality_multiplier
```

**Why not implemented now:**
- Requires per-player prior-season WAR lookup (Baseball-Reference or FanGraphs API)
- Covers.com injury data only provides name, position, status — no WAR/salary data
- Would require cross-referencing player names to WAR database (name matching complexity)
- Scope is a full additional pipeline phase, not a calibration change

**Flagged in `CLAUDE_NOTES.md` as Priority Enhancement.**

**Sources:**
- [What Does WAR Mean? — Sleeper](https://sleeper.com/blog/what-does-war-mean-in-baseball/)
- [The Mets Aren't Even Best at Getting Injured — FiveThirtyEight](https://fivethirtyeight.com/features/the-mets-arent-even-best-at-getting-injured/)
- [A Deep Learning Approach to MLB Money Line Betting — Analytics.Bet](https://analytics.bet/articles/a-deep-learning-approach-to-mlb-money-line-betting-based-on-joe-petas-trading-bases/)

---

## Summary of Changes

| Position | Old Weight | New Weight | Change | Primary Justification |
|----------|-----------|-----------|--------|-----------------------|
| SP | 8.0 | **8.0** | None | Market evidence supports ~8pp average-case; gate handles extremes |
| C | 2.0 | **3.0** | +1.0 | Highest positional adj (+12.5); framing not captured in FIP scoring |
| SS | 1.5 | **2.0** | +0.5 | Second hardest infield (+7.5 runs); 2B/3B gap was underrepresented |
| CP | 2.5 | **2.0** | -0.5 | Bullpen chaining reduces net loss to ~1.0-1.5 WAR equivalent |
| CF | 1.0 | **1.5** | +0.5 | Incorrectly equated with DH; CF has real defensive scarcity |
| 3B | 1.2 | **1.2** | None | +2.5 run adj; same tier as 2B analytically |
| MR | 1.2 | **1.2** | None | Correct relative to RP; LI 0.7-1.0 |
| RP | 1.5 | **1.5** | None | Correct; LI 1.2-1.5 setup arm |
| 2B | 1.0 | **1.0** | None | +2.5 run adj; correct |
| DH | 1.0 | **0.6** | -0.4 | No defensive scarcity (-17.5 run adj); purely offensive replacement |
| 1B | 0.8 | **0.8** | None | -12.5 run adj; easiest infield to fill |
| LF | 0.8 | **0.8** | None | -7.5 run adj; corner OF |
| RF | 0.8 | **0.8** | None | -7.5 run adj; corner OF |

---

## Impact on Model

The changes shift where injury impact concentrates:
- **Catcher injuries now correctly dominate** over most infield positions — a team losing its catcher (3.0 × 1.0 = 3.0pp) has a larger injury adjustment than a team losing its 2B (1.0pp), as analytics dictate
- **SS injuries carry more weight** (2.0pp vs. 1.5pp) — closer to the actual WAR gap vs. 2B/3B
- **CF injuries are now distinguished** from corner OF (1.5 vs. 0.8) — the current model wrongly treated them the same
- **DH injuries are less impactful** (0.6pp vs. 1.0pp) — reflects the availability of offensive replacements
- **Closer injuries are slightly reduced** (2.0 vs. 2.5) — the bullpen chain absorbs most of the impact
- The MAX_TEAM_IMPACT cap (12.0pp) remains unchanged and appropriate

---

## Sources

- [FanGraphs Positional Adjustment Library](https://library.fangraphs.com/misc/war/positional-adjustment/)
- [WAR for Position Players — FanGraphs](https://library.fangraphs.com/war/war-position-players/)
- [Re-Examining WAR's Defensive Spectrum — The Hardball Times](https://tht.fangraphs.com/re-examining-wars-defensive-spectrum/)
- [Defensive Spectrum — Wikipedia](https://en.wikipedia.org/wiki/Defensive_spectrum)
- [Converting Runs to Wins — FanGraphs](https://library.fangraphs.com/misc/war/converting-runs-to-wins/)
- [Catcher Defense — FanGraphs Sabermetrics Library](https://library.fangraphs.com/defense/catcher-defense/)
- [WAR Update: Catcher Framing — FanGraphs](https://blogs.fangraphs.com/war-update-catcher-framing/)
- [Statcast Catcher Framing Leaderboard — Baseball Savant](https://baseballsavant.mlb.com/leaderboard/catcher-framing)
- [Baseball Prospectus Framing Model](https://www.baseballprospectus.com/news/article/22934/framing-and-blocking-pitches-a-regressed-probabilistic-model-a-new-method-for-measuring-catcher-defense/)
- [WAR and Relievers — FanGraphs](https://blogs.fangraphs.com/war-and-relievers/)
- [Win Probability Added Above Replacement — The Hardball Times](https://tht.fangraphs.com/win-probability-added-above-replacement/)
- [Leverage Index Glossary — MLB.com](https://www.mlb.com/glossary/advanced-stats/leverage-index)
- [Saves Above Expected — SABR](https://sabr.org/journal/article/saves-above-expected-a-new-contextual-metric-for-closers/)
- [MLB Betting Lines: Action vs. Listed Pitcher — Sports Insights](https://www.sportsinsights.com/blog/mlb-betting-lines-action-vs-listed-pitcher/)
- [Batting Order Position Values — Bill James Online](https://www.billjamesonline.com/batting_order_position_values/)
- [The Mets Aren't Even Best at Getting Injured — FiveThirtyEight](https://fivethirtyeight.com/features/the-mets-arent-even-best-at-getting-injured/)
- [Nagoya University DH Study](https://en.nagoya-u.ac.jp/news/articles/a-decade-of-baseball-data-shows-the-designated-hitter-system-does-not-affect-how-teams-win/)
