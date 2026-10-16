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
# Erdős Problem 1154

*References:*
- [erdosproblems.com/1154](https://www.erdosproblems.com/1154)
- [ErVo66] Erdős, Paul and Volkmann, Bodo, Additive Gruppen mit vorgegebener Hausdorffscher
  Dimension. J. Reine Angew. Math. (1966), 203--208.
- [EdMi01] Edgar, G. A. and Miller, Chris, Hausdorff dimension, analytic sets and transcendence.
  Real Anal. Exchange (2001/02), 335--339.
- [EdMi03] Edgar, G. A. and Miller, Chris, Borel subrings of the reals. Proc. Amer. Math. Soc.
  (2003), 1121--1129.
- [Ma16b] Mauldin, R. Daniel, Subfields of ℝ with arbitrary Hausdorff dimension. Math.
  Proc. Cambridge Philos. Soc. (2016), 157--165.

-/

@[expose] public section

open scoped ENNReal Cardinal
open Set MeasureTheory

namespace Erdos1154

/-- The endpoint $\alpha = 0$ of `erdos_1154.parts.ii` is witnessed by $\mathbb{Q}$. -/
@[category test, AMS 28]
theorem erdos_1154.variants.exists_subfield_dimH_eq_zero :
    ∃ R : Subfield ℝ, dimH (R : Set ℝ) = 0 := by
  refine ⟨⊥, Set.Countable.dimH_zero <| (countable_range ((↑) : ℚ → ℝ)).mono ?_⟩
  simpa using SetLike.coe_subset_coe.2 (bot_le : ⊥ ≤ (Rat.castHom ℝ).fieldRange)

-- EDITABLE BEGIN
-- EDITABLE END

/-- The endpoint $\alpha = 1$ of `erdos_1154.parts.ii` is witnessed by $\mathbb{R}$. -/
@[category test, AMS 28]
theorem erdos_1154.variants.exists_subfield_dimH_eq_one :
    ∃ R : Subfield ℝ, dimH (R : Set ℝ) = 1 := by
  -- EDITABLE BEGIN
  refine ⟨⊤, ?_⟩
  rw [Subfield.coe_top]
  exact Real.dimH_univ
  -- EDITABLE END

end Erdos1154
