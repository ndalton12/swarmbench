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
# Invariant Subspace Problem

*Reference:* [Wikipedia](https://en.wikipedia.org/wiki/Invariant_subspace_problem),
[Chalendar-Partington](https://arxiv.org/abs/2507.21834)
-/

@[expose] public section

namespace InvariantSubspaceProblem

variable {H : Type*} [NormedAddCommGroup H]

/-- `ClosedInvariantSubspace T` is the type of non-trivial (different from `H` and `{0}`) closed
subspaces of a complex vector space `H` that are invariant under the action of linear map `T`. -/
structure ClosedInvariantSubspace [Module ℂ H] (T : H →L[ℂ] H) where
  toSubspace : Submodule ℂ H
  ne_bot : toSubspace ≠ ⊥
  ne_top : toSubspace ≠ ⊤
  is_closed : IsClosed (toSubspace : Set H)
  is_fixed : toSubspace.map T.toLinearMap ≤ toSubspace

-- EDITABLE BEGIN
-- EDITABLE END

/--
Every (bounded) linear operator `T : H → H` on a finite-dimensional normed space `H` of dimension
at least 2 has a non-trivial (closed) `T`-invariant subspace. Since `ℂ` is algebraically closed,
`T` has an eigenvector `v ≠ 0`, and the line `ℂ ∙ v` is such a subspace.

`H` is a complex normed space: with a bare `Module ℂ H` unrelated to the norm, finite-dimensional
subspaces need not be closed, and the statement fails already in complex dimension `2`. -/
@[category research solved, AMS 47]
theorem Invariant_subspace_problem_finite_dimensional [NormedSpace ℂ H] (h : FiniteDimensional ℂ H)
    (hdim : 2 ≤ Module.rank ℂ H) (T : H →L[ℂ] H) : Nonempty (ClosedInvariantSubspace T) := by
  -- EDITABLE BEGIN
  have hnt : Nontrivial H := by
    rw [← rank_pos_iff_nontrivial (R := ℂ)]
    exact lt_of_lt_of_le (by norm_num) hdim
  obtain ⟨c, hc⟩ := Module.End.exists_eigenvalue (T : H →ₗ[ℂ] H)
  obtain ⟨v, hv⟩ := hc.exists_hasEigenvector
  have hv0 : v ≠ 0 := hv.2
  have h2 : 2 ≤ Module.finrank ℂ H := by
    have := hdim
    rw [← Module.finrank_eq_rank] at this
    exact_mod_cast this
  refine ⟨⟨Submodule.span ℂ {v}, ?_, ?_, Submodule.closed_of_finiteDimensional _, ?_⟩⟩
  · rw [Ne, Submodule.span_singleton_eq_bot]
    exact hv0
  · intro htop
    have h1 := finrank_span_singleton (K := ℂ) hv0
    rw [htop, finrank_top] at h1
    omega
  · rw [Submodule.map_le_iff_le_comap, Submodule.span_le]
    intro x hx
    rw [Set.mem_singleton_iff] at hx
    rw [hx]
    show T v ∈ Submodule.span ℂ {v}
    rw [show T v = c • v from hv.apply_eq_smul]
    exact Submodule.smul_mem _ _ (Submodule.mem_span_singleton_self v)
  -- EDITABLE END

end InvariantSubspaceProblem
