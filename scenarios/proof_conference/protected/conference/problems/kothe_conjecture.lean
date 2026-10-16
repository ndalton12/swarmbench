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
# Köthe conjecture

*Reference:* [Wikipedia](https://en.wikipedia.org/wiki/K%C3%B6the_conjecture)
-/

@[expose] public section

open Ideal TwoSidedIdeal Polynomial

open Matrix

universe u v w

variable {R : Type*}

variable [Ring R]

namespace Koethe

/-- Say a subset `I` of a ring `R` is nilpotent if all its elements are nilpotent. -/
def IsNil {S : Type*} [SetLike S R] (I : S) := ∀ i ∈ I, IsNilpotent i

-- TODO(lezeau): add some basic API and already known results for nil ideals

variable (R) in
/-- The *Kothe Radical* of a ring `R` is the sum of all (two-sided) nil ideals of `R`.
Tags: Kothe Radical, upper nilradical-/
def KotheRadical : TwoSidedIdeal R := sSup {I : TwoSidedIdeal R | IsNil I}

-- This is often denoted `Nil*(R)`
local notation "Nil* " R => KotheRadical R

/- ### Basic API for nil ideals -/

/-- A subset of a nil subset is nil. -/
@[category API, AMS 16]
theorem IsNil.mono {S : Type*} [SetLike S R] {I J : S} (h : (I : Set R) ⊆ J) (hJ : IsNil J) :
    IsNil I :=
  fun i hi => hJ i (h hi)

/-- The zero two-sided ideal is nil. -/
@[category API, AMS 16]
theorem isNil_bot : IsNil (⊥ : TwoSidedIdeal R) := fun x hx => by
  rw [TwoSidedIdeal.mem_bot] at hx
  exact hx ▸ IsNilpotent.zero

/-- The sum of two nil two-sided ideals is nil. -/
@[category API, AMS 16]
theorem IsNil.sup {I J : TwoSidedIdeal R} (hI : IsNil I) (hJ : IsNil J) : IsNil (I ⊔ J) := by
  intro x hx
  obtain ⟨a, ha, b, hb, rfl⟩ := TwoSidedIdeal.mem_sup.mp hx
  obtain ⟨m, hm⟩ := hJ b hb
  -- Modulo `I`, the element `a + b` is `b`, hence `(a + b) ^ m ∈ I`.
  have hmem : (a + b) ^ m ∈ I := by
    have ha' : (a : I.ringCon.Quotient) = 0 := I.ringCon.eq.mpr ha
    rw [TwoSidedIdeal.mem_iff, ← I.ringCon.eq, RingCon.coe_pow, RingCon.coe_add, ha', zero_add,
      ← RingCon.coe_pow, hm]
  obtain ⟨k, hk⟩ := hI _ hmem
  exact ⟨m * k, by rw [pow_mul, hk]⟩

variable (R) in
/-- The Köthe radical is a nil ideal: every element of `Nil* R` is nilpotent. This is a standard
fact which does not depend on the Köthe conjecture. -/
@[category API, AMS 16]
theorem isNil_kotheRadical : IsNil (Nil* R) := by
  -- The union of all nil two-sided ideals is itself a nil two-sided ideal.
  let K : TwoSidedIdeal R := .mk' {x | ∃ I : TwoSidedIdeal R, IsNil I ∧ x ∈ I}
    ⟨⊥, isNil_bot, TwoSidedIdeal.zero_mem ⊥⟩
    (by
      rintro x y ⟨I, hI, hx⟩ ⟨J, hJ, hy⟩
      exact ⟨I ⊔ J, hI.sup hJ,
        add_mem (TwoSidedIdeal.mem_sup_left hx) (TwoSidedIdeal.mem_sup_right hy)⟩)
    (by rintro x ⟨I, hI, hx⟩; exact ⟨I, hI, neg_mem hx⟩)
    (by rintro x y ⟨I, hI, hy⟩; exact ⟨I, hI, I.mul_mem_left _ _ hy⟩)
    (by rintro x y ⟨I, hI, hx⟩; exact ⟨I, hI, I.mul_mem_right _ _ hx⟩)
  have hK : IsNil K := fun x hx => by
    obtain ⟨I, hI, hx⟩ := (TwoSidedIdeal.mem_mk' _ _ _ _ _ _ x).mp hx
    exact hI x hx
  refine hK.mono (TwoSidedIdeal.le_iff.mp (sSup_le fun I hI => ?_))
  intro x hx
  exact (TwoSidedIdeal.mem_mk' _ _ _ _ _ _ x).mpr ⟨I, hI, hx⟩

/-- If `L` is a nil left ideal, then so is `L * y` for any `y`. -/
@[category API, AMS 16]
theorem IsNil.map_mulRight {L : Ideal R} (hL : IsNil L) (y : R) :
    IsNil (Submodule.map (LinearMap.mulRight R y) L) := by
  intro z hz
  obtain ⟨x, hx, rfl⟩ := Submodule.mem_map.mp hz
  obtain ⟨k, hk⟩ := hL _ (L.mul_mem_left y hx)
  refine ⟨k + 1, ?_⟩
  rw [LinearMap.mulRight_apply, pow_succ, ← mul_assoc, mul_pow_mul, hk, mul_zero, zero_mul]

-- EDITABLE BEGIN
-- EDITABLE END

/-- The **Köthe conjecture**: In any ring, the sum of two nil left ideals is nil. -/
@[category research open, AMS 16]
theorem KotheConjecture (I J : Ideal R) (hI : IsNil I) (hJ : IsNil J) : IsNil (I + J) := by
  -- EDITABLE BEGIN
  sorry
  -- EDITABLE END

end Koethe
