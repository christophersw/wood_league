# Analysis Math and Classification

This document explains how move quality, player accuracy, and classifications are computed.

## Stockfish pipeline

### Engine evaluation

Stockfish returns centipawn (`cp`) evaluations from White's perspective.

- Positive cp favors White
- Negative cp favors Black

Mate scores are normalized with `score(mate_score=10000)`: all forced-mate positions are
assigned a flat value of ±10000 cp regardless of the number of moves to mate (mate in 1
and mate in 10 are both treated as 10000 cp). This means a move that allows mate in 3
instead of delivering mate in 1 will show CPL = 0; the classification heuristics (see
below) are responsible for distinguishing such cases.

### Per-move centipawn loss (CPL)

Stockfish evaluations are always from White's perspective, so the sign must be flipped
for Black before computing CPL:

- **White:** $\text{eval}_{\text{mover}} = \text{cp}$ (no change)
- **Black:** $\text{eval}_{\text{mover}} = -\text{cp}$ (negate to get Black's perspective)

CPL is then:

$$
\text{CPL} = \max\big(0,\; \text{eval}_{\text{mover,before}} - \text{eval}_{\text{mover,after}}\big)
$$

where both evaluations are expressed from the mover's perspective using the sign
convention above.

### Win% conversion

Win% uses Lichess' empirical sigmoid:

$$
\text{Win\%} = \frac{100}{1 + e^{-0.00368208 \times \text{cp}}}
$$

where `cp` is from the mover's perspective (i.e., after the sign flip described above).

### Per-move accuracy

Accuracy is based on Win% drop from mover perspective:

$$
\text{Accuracy\%} = 103.1668100711649 \times e^{-0.04354415386753951 \times (\text{Win\%}_{\text{before}} - \text{Win\%}_{\text{after}})} - 3.166924740191411
$$

Clamp to `[0, 100]`.

### Game accuracy aggregation

Per-player game accuracy is:

$$
\text{Game Accuracy} = \frac{\text{WeightedMean} + \text{HarmonicMean}}{2}
$$

- **Weighted mean** uses volatility-based weights derived from a sliding window over
  Win% values. For each move $i$, the weight $w_i$ is the standard deviation of Win%
  across a window of $k$ surrounding moves (window size $k$ is fixed at 8, centered on
  the move where possible and truncated at game boundaries). Higher volatility — i.e.,
  sharper swings in the position — gives a move more influence on the weighted mean.
- **Harmonic mean** penalizes severe mistakes.

$$
\text{HarmonicMean} = \frac{n}{\sum_{i=1}^{n} \frac{1}{\max(\text{MoveAcc}_i,\;\varepsilon)}}
$$

where $\varepsilon = 0.001$ and $n$ is the number of moves by the player being evaluated.

### ACPL

Average centipawn loss, computed **per player** (i.e., $n$ is the number of moves made
by the player being evaluated, not the total number of moves in the game):

$$
\text{ACPL} = \frac{1}{n} \sum_{i=1}^{n} \text{CPL}_i
$$

### Stockfish move classification thresholds

Classifications are evaluated in the order listed; the **first matching classification
applies**.

A move is considered a **capture or sacrifice** if it results in a net material loss for
the mover according to static exchange evaluation (SEE): i.e., the mover gives up a
piece or pawn and the resulting exchange is evaluated as losing material for them. Pure
captures that win or break even on material do not qualify.

| Classification | Criteria |
|---|---|
| Brilliant | `CPL < 10`, move is a capture or sacrifice (see above), mover Win% before `< 70`, second-best move gap `>= 150 cp` |
| Great | `CPL < 10` and second-best move gap `>= 80 cp` |
| Best | `CPL < 10` and not Brilliant or Great |
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
\text{cp}_{\text{equiv}} = 111.714640912 \times \tan(1.5620688421 \times Q)
$$

`Q` is clamped to avoid singularity near `±1`.

### Lc0 move quality

Win% loss from mover perspective:

$$
\Delta\text{Win\%} = \max\big(0,\;\text{Win\%}_{\text{mover,before}} - \text{Win\%}_{\text{mover,after}}\big)
$$

### Lc0 classification thresholds

Classifications are evaluated in the order listed; the **first matching classification
applies**.

A move is considered a **capture or sacrifice** using the same SEE-based definition as
in the Stockfish pipeline above.

| Classification | Win% loss criterion |
|---|---|
| Brilliant | `Δ <= 1%`, move is a capture or sacrifice (see above), mover Win% before `< 70`, second-best gap `>= 10%` |
| Great | `Δ <= 1%` and second-best gap `>= 6%` |
| Best | `Δ <= 1%` and not Brilliant or Great |
| Excellent | `1% < Δ < 2%` |
| Inaccuracy | `2% <= Δ < 5%` |
| Mistake | `5% <= Δ < 10%` |
| Blunder | `Δ >= 10%` |

---

## References

- Lichess Win% model: <https://github.com/lichess-org/scalachess/blob/master/core/src/main/scala/eval.scala>
- Lichess accuracy aggregation: <https://github.com/lichess-org/lila/blob/master/modules/analyse/src/main/AccuracyPercent.scala>
- Lc0 docs: <https://lczero.org/>
- Updates surfaced via Kagi assistant: <https://kagi.com/assistant/2d10eafe-0e86-4831-bec6-5f3a6102348a>
