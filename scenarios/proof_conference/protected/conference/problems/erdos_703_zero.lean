/-
Copyright 2026 The Formal Conjectures Authors.

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
# Erdős Problem 703

*References:*
- [erdosproblems.com/703](https://www.erdosproblems.com/703)
- [Er75f] Erdős, Paul, _On some problems of elementary and combinatorial geometry_. Ann. Mat.
  Pura Appl. (4) (1975), 99-108.
- [Er76b] Erdős, P., _Problems and results in graph theory and combinatorial analysis_.
  Proceedings of the Fifth British Combinatorial Conference (Univ. Aberdeen, Aberdeen, 1975)
  (1976), 169-192.
- [Er81] Erdős, P., _On the combinatorial problems which I would most like to see solved_.
  Combinatorica (1981), 25-42.
- [Er82e] Erdős, Paul, _Some of my favourite problems which recently have been solved_. (1982),
  59--79.
- [FrFu84b] Frankl, P. and Füredi, Z., _On hypergraphs without two edges intersecting in a given
  number of vertices_. J. Combin. Theory Ser. A (1984), 230-236.
- [Fr77b] Frankl, P., _An intersection problem for finite sets_. Acta Math. Acad. Sci. Hungar.
  (1977), 371-373.
- [FrRo87] Frankl, Peter and Rödl, Vojtech, _Forbidden intersections_. Trans. Amer. Math. Soc.
  (1987), 259-286.
-/

@[expose] public section

open Finset

namespace Erdos703

/-- `T n r` is maximal such that there exists a family $\mathcal{F}$ of subsets of
$\{1,\ldots,n\}$ of size `T n r` such that $\lvert A\cap B\rvert\neq r$ for all
$A,B\in \mathcal{F}$ (including $A=B$). -/
noncomputable def T (n r : ℕ) : ℕ :=
  sSup {k | ∃ 𝓕 : Finset (Finset (Fin n)),
    (∀ A ∈ 𝓕, ∀ B ∈ 𝓕, (A ∩ B).card ≠ r) ∧ 𝓕.card = k}

-- EDITABLE BEGIN
-- EDITABLE END

/-- It is trivial that $T(n,0)=2^{n-1}$. -/
@[category textbook, AMS 5]
theorem erdos_703.variants.zero (n : ℕ) (hn : 1 ≤ n) : T n 0 = 2 ^ (n - 1) := by
  -- EDITABLE BEGIN
  sorry
  -- EDITABLE END

end Erdos703
