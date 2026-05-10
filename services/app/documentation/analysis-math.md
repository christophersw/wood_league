# Analysis Math and Classification

This document explains how move quality, player accuracy, and classifications are computed.

## Stockfish pipeline

### Engine evaluation

Stockfish returns centipawn (`cp`) evaluations from White's perspective.

- Positive cp favors White
- Negative cp favors Black

Mate scores are normalized with `score(mate_score=10000)`: all forced-mate positions are
assigned a flat value of ±10000 cp regardless of the number of moves to mate (mate in 1
and mate in 10 are both treated as 10000 cp). To preserve the quality difference
between "mate in 1 played" and "mate in 1 turned into mate in 10 played" — both of
which would otherwise show CPL = 0 — an additive **mate-distance penalty** is applied
on top of the regular CPL (see below).

#### Mate-distance heuristic

The engine reports forced mates as a signed ply count. Let

- $M_b$ = mover-frame mate plies before the move (positive = mover delivers mate;
  $\text{None}$ if no forced mate).
- $M_a$ = mover-frame mate plies after the move.

Then the additive penalty $\Delta_{\text{mate}}$ is:

| Case | Penalty |
|------|---------|
| $M_b \le 0$ or $M_b = \text{None}$ (mover had no mate) | $0$ |
| $M_b > 0$ and ($M_a \le 0$ or $M_a = \text{None}$) — mover lost the mate | $500$ cp (Blunder tier) |
| $M_b > 0$ and $M_a > 0$ — mover still has mate but possibly took longer | $50 \cdot \max(0,\; M_a - (M_b - 1))$ cp |

A correctly-played mate satisfies $M_a = M_b - 1$ and the penalty is $0$.
A 1-ply detour adds 50 cp (Inaccuracy), 2 plies adds 100 cp (Mistake), 6+ plies
adds 300+ cp (Blunder). The mover-frame is preserved from White's perspective for
White moves and negated for Black moves before evaluating $M_b$ and $M_a$.

The total CPL fed into classification is

$$\text{CPL}_{\text{total}} = \max\big(0,\; \text{eval}_{\text{mover,before}} - \text{eval}_{\text{mover,after}}\big) + \Delta_{\text{mate}}.$$

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
  the **interleaved (game-wide) Win% sequence** — the Win% from White's frame after
  every ply, both colours interleaved in move order. This matches Lichess's
  `AccuracyPercent.scala`. For a game with $n$ plies the window size is

  $$k = \mathrm{clamp}\!\left(\left\lfloor\frac{n}{10}\right\rfloor,\; 2,\; 8\right).$$

  For each ply $i$ the raw weight is the population standard deviation of Win%
  across the $k$-ply window beginning at that ply (Lichess uses
  `allWinPercents.sliding(windowSize)` over the interleaved sequence). The first
  $k-2$ plies are front-padded by repeating the leading window so that early moves
  receive a stable volatility estimate. Each weight is then clamped to
  $[0.5,\; 12]$ — a floor so quiet positions still contribute and a ceiling so a
  single explosive swing cannot dominate the weighted mean. The per-player weighted
  mean averages each player's accuracies under their own moves' weights.
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

#### SEE edge-case contract

The SEE pass used by the classification heuristics handles the following cases:

- **En passant.** The captured pawn is removed from the square one rank behind the
  destination from the mover's perspective (rank 5 when White captures, rank 4 when
  Black captures). The destination square value is set to a pawn (100 cp).
- **Promotion on the initial capture.** When the captured-piece move is itself a
  promoting capture, the swap-list seed gain is the captured piece's value plus the
  promotion bonus `(promo_value − pawn_value)`, and the piece sitting on the target
  square for any subsequent recapture is the promoted piece. A promotion to queen on
  capture of an undefended rook therefore scores `500 + (900 − 100) = 1300` cp.
- **Promotion during the exchange.** A pawn that arrives on its eighth rank as part
  of a recapture sequence is treated as a queen for value-on-target purposes
  (Stockfish convention).
- **Absolute pins.** Any attacker that is absolutely pinned to its own king is
  excluded from the swap list, **unless** the destination square lies on the pin ray
  (i.e., capturing on the target does not break the pin). Pin rays are determined
  with `python-chess`'s `Board.pin(color, square)`.

The SEE iteration mutates a working occupancy bitboard to reveal x-ray attackers and
removes both the original mover and any recapturing piece from that occupancy. The
swap list is reduced by the standard minimax: `gain[i-1] = -max(-gain[i-1], gain[i])`.
The capture-or-sacrifice predicate is `SEE < 0` (strictly negative).

The SEE pass is undefined for positions in which the side to move is in check; the
classification layer is responsible for short-circuiting those cases.

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
