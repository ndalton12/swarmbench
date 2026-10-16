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
# Erdős Problem 742

*References:*
- [erdosproblems.com/742](https://www.erdosproblems.com/742)
- [Pl75] Plesník, Ján, Critical graphs of given diameter. Acta Fac. Rerum Natur. Univ. Comenian.
  Math. 30 (1975), 71-93.
- [CaHa79] Caccetta, L. and Häggkvist, R., On diameter critical graphs.
  Discrete Math. 28 (1979), 223-229.
- [Fa87] Fan, Genghua, On diameter 2-critical graphs. Discrete Math. 67 (1987), 235-240.
- [Fü92] Füredi, Zoltán, The maximum number of edges in a minimal graph of diameter 2.
  J. Graph Theory 16 (1992), 81-98.
-/

@[expose] public section

open SimpleGraph

namespace Erdos742

variable {V : Type*} [Fintype V] [DecidableEq V]

/-- A graph is diameter-2-critical if it has diameter $2$ and removing any edge
increases the diameter beyond $2$. -/
def IsDiameter2Critical (G : SimpleGraph V) : Prop :=
  G.diam = 2 ∧ ∀ e ∈ G.edgeSet, (G.deleteEdges {e}).diam ≠ 2

-- EDITABLE BEGIN
-- EDITABLE END

/--
The complete bipartite graph $K_{a, b}$ has exactly $a \cdot b$ edges. The bound
$\lfloor n^2 / 4 \rfloor$ in the Murty-Simon conjecture is attained by the balanced
case $K_{\lceil n/2 \rceil, \lfloor n/2 \rfloor}$.
-/
@[category test, AMS 5]
theorem complete_bipartite_edge_count (a b : ℕ) :
    (completeBipartiteGraph (Fin a) (Fin b)).edgeSet.ncard = a * b := by
  -- EDITABLE BEGIN
  sorry
  -- EDITABLE END

end Erdos742
