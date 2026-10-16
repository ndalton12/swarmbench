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
# Moser's Worm

*Reference:* [Wikipedia](https://en.wikipedia.org/wiki/Moser%27s_worm_problem)
-/

@[expose] public section

open EuclideanGeometry MeasureTheory

namespace MoserWorm

/--
The set of worms is the set of curves of length (at most) 1.
We formalize this as the set of ranges of 1-Lipschitz functions from `[0,1]` to `ℝ²`.
-/
def Worms : Set (Set ℝ²) :=
    {s | ∃ f : (Set.Icc (0 : ℝ) (1 : ℝ)) → ℝ², LipschitzWith 1 f ∧ Set.range f = s}

/--
The set of covers is the set of (measurable) sets
that cover every worm by translation and rotation.
-/
def WormCovers : Set (Set ℝ²) :=
    {X | MeasurableSet X ∧ ∀ w ∈ Worms, ∃ (e : ℝ² ≃ₗᵢ[ℝ] ℝ²) (v : ℝ²),
      e.toLinearEquiv.det = 1 ∧ w ⊆ (fun x => e x + v) '' X}

-- EDITABLE BEGIN
-- EDITABLE END

/--
A disc of radius 1 / 2 is a worm cover.

This follows by translating the center of the disc to the midpoint of the worm.
-/
@[category textbook, AMS 52]
theorem disc_mem_worm_covers : Metric.closedBall 0 0.5 ∈ WormCovers := by
  -- EDITABLE BEGIN
  refine ⟨measurableSet_closedBall, ?_⟩
  rintro w ⟨f, hf, rfl⟩
  refine ⟨LinearIsometryEquiv.refl ℝ _, f ⟨1/2, by constructor <;> norm_num⟩,
    LinearEquiv.det_refl .., ?_⟩
  rintro _ ⟨t, rfl⟩
  refine ⟨f t - f ⟨1/2, by constructor <;> norm_num⟩, ?_, by simp⟩
  simp only [Metric.mem_closedBall, dist_zero_right]
  have h := hf.dist_le_mul t ⟨1/2, by constructor <;> norm_num⟩
  simp only [NNReal.coe_one, one_mul] at h
  rw [dist_eq_norm] at h
  refine h.trans ?_
  obtain ⟨t, ht1, ht2⟩ := t
  simp only [Subtype.dist_eq, Real.dist_eq]
  rw [abs_le]
  constructor <;> linarith
  -- EDITABLE END

end MoserWorm
