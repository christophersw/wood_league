# Analysis Math and Classification

This document explains how move quality, player accuracy, and classifications are computed.

## Stockfish pipeline

### Engine evaluation

Stockfish returns centipawn (`cp`) evaluations from White's perspective.

- Positive cp favors White
- Negative cp favors Black

Mate scores are normalized with `score(mate_score=10000)`.

### Per-move centipawn loss (CPL)

For each move, evaluate position before and after the move from the mover's perspective:

$$
\text{CPL} = \max\big(0,\; \text{eval}_{\text{before}} - \text{eval}_{\text{after}}\big)
$$

### Win% conversion

Win% uses Lichess' empirical sigmoid:

$$
\text{Win\%} = 50 + 50 \times \left(\frac{2}{1 + e^{-0.00368208 \times \text{cp}}} - 1\right)
$$

### Per-move accuracy

Accuracy is based on Win% drop from mover perspective:

$$
\text{Accuracy\%} = 103.1668100711649 \times e^{-0.04354415386753951 \times (\text{Win\%}_{\text{before}} - \text{Win\%}_{\text{after}})} - 3.166924740191411 + 1
$$

Clamp to `[0, 100]`.

### Game accuracy aggregation

Per-player game accuracy is:

$$
\text{Game Accuracy} = \frac{\text{WeightedMean} + \text{HarmonicMean}}{2}
$$

- Weighted mean uses volatility-based weights from sliding Win% windows.
- Harmonic mean penalizes severe mistakes.

$$
\text{HarmonicMean} = \frac{n}{\sum_{i=1}^{n} \frac{1}{\max(\text{MoveAcc}_i,\;\varepsilon)}}
$$

where `\varepsilon = 0.001`.

### ACPL

Average centipawn loss:

$$
\text{ACPL} = \frac{1}{n} \sum_{i=1}^{n} \text{CPL}_i
$$

### Stockfish move classification thresholds

| Classification | Criteria |
|---|---|
| Brilliant | `CPL < 10`, capture/sacrifice heuristic, mover Win% before `< 70`, second-best gap `>= 150 cp` |
| Great | `CPL < 10` and second-best gap `>= 80 cp` |
| Best | `CPL < 10` and not Brilliant/Great |
| Excellent | `10 <= CPL < 50` |
| Inaccuracy | `50 <= CPL < 100` |
| Mistake | `100 <= CPL < 300` |
| Blunder | `CPL >= 300` |

---

## Lc0 pipeline

Lc0 provides WDL probabilities, so move quality is measured in Win% space directly.

### WDL representation

Lc0 reports `wdl_win`, `wdl_draw`, `wdl_loss` (permille values summing to 1000).

The app stores values from White's perspective.

### Q value to centipawn equivalent

For display, Lc0 Q is converted approximately:

$$
\text{cp}_{\text{equiv}} = 111.71 \times \tan(1.56 \times Q)
$$

`Q` is clamped to avoid singularity near `±1`.

### Lc0 move quality

Win% loss from mover perspective:

$$
\Delta\text{Win\%} = \max\big(0,\;\text{Win\%}_{\text{mover,before}} - \text{Win\%}_{\text{mover,after}}\big)
$$

### Lc0 classification thresholds

| Classification | Win% loss criterion |
|---|---|
| Brilliant | `Δ <= 1%`, capture heuristic, mover Win% before `< 70`, second-best gap `>= 10%` |
| Great | `Δ <= 1%` and second-best gap `>= 6%` |
| Best | `Δ <= 1%` and not Brilliant/Great |
| Excellent | `1% < Δ < 2%` |
| Inaccuracy | `2% <= Δ < 5%` |
| Mistake | `5% <= Δ < 10%` |
| Blunder | `Δ >= 10%` |

---

## References

- Lichess Win% model: <https://github.com/lichess-org/scalachess/blob/master/core/src/main/scala/eval.scala>
- Lichess accuracy aggregation: <https://github.com/lichess-org/lila/blob/master/modules/analyse/src/main/AccuracyPercent.scala>
- Lc0 docs: <https://lczero.org/>
