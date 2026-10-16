/-
Copyright 2025 The Formal Conjectures Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-/
module

public import FormalConjecturesUtil

/-!
# Packing

This file contains a number of open problems related to the minimal size of a square (or circle)
that can contain a given number of unit squares (or circles).
In each case, we provide a known upper bound, and ask for the least such size.

*References:*
- [Wikipedia on packing of squares](https://en.wikipedia.org/wiki/Square_packing)
- [Wikipedia on packing of circles in a circle](https://en.wikipedia.org/wiki/Circle_packing_in_a_circle)
- [Wikipedia on packing of circles in a square](https://en.wikipedia.org/wiki/Circle_packing_in_a_square)
- Friedman, Erich (2009), "Packing unit squares in squares: a survey and new results",
  Electronic Journal of Combinatorics, 1000, Dynamic Survey 7
- Pirl, U. (1969),
  ["Der Mindestabstand von $n$ in der Einheitskreisscheibe gelegenen Punkten"](https://doi.org/10.1002/mana.19690400110),
  Mathematische Nachrichten, 40: 111–124
- A website with visualizations of packings:
  [link](https://erich-friedman.github.io/packing/)
- [Erich Friedman, Squares in Circles](https://erich-friedman.github.io/packing/squincir/)
- [The-Anh Vu-Le, Lean 4 proof of Squares in Circles](https://github.com/vltanh/lean4-squares-in-circles)
- [Kenta Kitamura, Lean proof of the exact three-square minimum for Formal Conjectures](https://github.com/KitaKen1/three-squares-in-a-circle-lean/blob/87bd2b6915933cf608a3cae6263c2500fe81f7ec/lean/ThreeSquares/Compressed/Main.lean#L216-L219)
-/

@[expose] public section

open EuclideanGeometry

open scoped NNReal

universe u

namespace SquarePacking

/--
A square of a particular side length as a subset of the Euclidean plane.
Not including border, so that squares that touch at the border are disjoint,
but a square internal to another shape is a subset of that shape.
-/
def Square (side : ℝ) : Set ℝ² :=
  {p : ℝ² | 0 < p 0 ∧ p 0 < side ∧ 0 < p 1 ∧ p 1 < side}

/--
The unit square as a subset of the Euclidean plane.
-/
def UnitSquare : Set ℝ² := Square 1

/--
A circle of a particular radius as a subset of the Euclidean plane.
The radius is a nonnegative real, so that `Circle r` is always the disc of radius $r$.
Not including border, so that circles that touch at the border are disjoint,
but a circle internal to another shape is a subset of that shape.
-/
def Circle (r : ℝ≥0) : Set ℝ² :=
  {p : ℝ² | p 0 ^ 2 + p 1 ^ 2 < (r : ℝ) ^ 2}

/--
The unit circle as a subset of the Euclidean plane.
-/
def UnitCircle : Set ℝ² := Circle 1

/--
A structure representing a packing of `n` isometric embeddings
of a set `s` inside a (presumably larger) set `S`.
-/
structure Packing (n : ℕ) (s : Set ℝ²) (S : Set ℝ²) where
  /-- The isometric equivalences
  that represent the transformations of the base shape to their locations in the packing. -/
  embeddings : Fin n → (ℝ² ≃ᵢ ℝ²)
  /-- The images of the embeddings are pairwise disjoint -/
  disjoint : Pairwise fun i j => Disjoint (embeddings i '' s) (embeddings j '' s)
  /-- The images of the embeddings are all inside the larger set `S` -/
  inside : ∀ i : Fin n, embeddings i '' s ⊆ S

/--
The degenerate circle is empty.
-/
@[category test, AMS 51]
theorem circle_zero : Circle 0 = ∅ := by
  ext p
  simp only [Circle, Set.mem_ofPred_eq, Set.mem_empty_iff_false, iff_false, not_lt,
    NNReal.coe_zero, zero_pow, ne_eq, OfNat.ofNat_ne_zero, not_false_eq_true]
  positivity

-- EDITABLE BEGIN
-- EDITABLE END

/--
What is the smallest circle that can contain 3 unit squares?

The least radius is $5\sqrt{17}/16$. The-Anh Vu-Le proved optimality in
September 2026. Kenta Kitamura gave a separate Lean proof of this exact
`IsLeast` statement using the `SquarePacking` definitions in this file.

References: [Wikipedia](https://en.wikipedia.org/wiki/Square_packing#In_a_circle),
[Friedman's table](https://erich-friedman.github.io/packing/squincir/),
[Vu-Le's Lean proof](https://github.com/vltanh/lean4-squares-in-circles), and
[Kitamura's FC-target Lean proof](https://github.com/KitaKen1/three-squares-in-a-circle-lean/blob/87bd2b6915933cf608a3cae6263c2500fe81f7ec/lean/ThreeSquares/Compressed/Main.lean#L216-L219).
-/
@[category research solved, AMS 51,
  formal_proof using lean4 at
    "https://github.com/KitaKen1/three-squares-in-a-circle-lean/blob/87bd2b6915933cf608a3cae6263c2500fe81f7ec/lean/ThreeSquares/Compressed/Main.lean#L216-L219"]
theorem least_three_square_packing_in_circle :
    IsLeast {r : ℝ≥0 | Nonempty (Packing 3 UnitSquare (Circle r))}
      answer(EVOLVE-VALUE) := by
  -- EDITABLE BEGIN
  sorry
  -- EDITABLE END

end SquarePacking
