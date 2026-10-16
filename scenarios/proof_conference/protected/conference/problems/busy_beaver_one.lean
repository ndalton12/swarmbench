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
# Busy Beaver

The Busy Beaver problem asks for the maximum number of steps that an n-state, 2-symbol Turing
machine can take before halting, when started on an empty tape.

*References:*

- [The Busy Beaver Challenge](https://wiki.bbchallenge.org/wiki/Main_Page)
-/

@[expose] public section

universe u v

open Turing BusyBeaver

namespace BusyBeaver

structure Candidate (n : ℕ) where
  Γ : Type
  Λ : Type
  Γ_fintype : Fintype Γ
  Γ_card : Fintype.card Γ = 2
  Γ_inhabited : Inhabited Γ
  Λ_fintype : Fintype Λ
  Λ_card : Fintype.card Λ = n
  Λ_inhabited : Inhabited Λ
  M : Machine Γ Λ
  M_isHalting : M.IsHalting

instance {n : ℕ} {M : Candidate n} : Fintype M.Γ := M.Γ_fintype
instance {n : ℕ} {M : Candidate n} : Fintype M.Λ := M.Λ_fintype
instance {n : ℕ} {M : Candidate n} : Inhabited M.Γ := M.Γ_inhabited
instance {n : ℕ} {M : Candidate n} : Inhabited M.Λ := M.Λ_inhabited

/--
`BB(n)` is the `n`-th Busy Beaver number.
*This is the maximum shifts function*, not the "number of ones function"
-/
noncomputable def BB (n : ℕ) : ℕ :=
  sSup { N | ∃ C : Candidate n, C.M.haltingNumber = N}

-- EDITABLE BEGIN
-- EDITABLE END

/-- The value of the Busy Beaver function for 1 state is 1. -/
@[category test, AMS 3]
theorem BB_1 : BB 1 = 1 := by
  -- EDITABLE BEGIN
  sorry
  -- EDITABLE END

end BusyBeaver
