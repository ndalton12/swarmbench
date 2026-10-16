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
# Erdős Problem 1

*Reference:* [erdosproblems.com/1](https://www.erdosproblems.com/1)
-/

@[expose] public section

open Filter

open scoped Topology Real

namespace Erdos1

/--
A finite set of naturals $A$ is said to be a sum-distinct set for $N \in \mathbb{N}$ if
$A\subseteq\{1, ..., N\}$ and the sums $\sum_{a\in S}a$ are distinct for all $S\subseteq A$
-/
abbrev IsSumDistinctSet (A : Finset ℕ) (N : ℕ) : Prop :=
    A ⊆ Finset.Icc 1 N ∧ (fun (⟨S, _⟩ : A.powerset) => S.sum id).Injective

-- EDITABLE BEGIN
-- EDITABLE END

/--
If $A\subseteq\{1, ..., N\}$ with $|A| = n$ is such that the subset sums $\sum_{a\in S}a$ are
distinct for all $S\subseteq A$ then
$$
  N \gg 2 ^ n.
$$

This conjecture is false. A machine-checked disproof constructs sum-distinct sets for which
$N / 2^n$ tends to zero.
-/
@[category research solved, AMS 5 11, formal_proof using lean4 at
  "https://github.com/tadamcz/erdos1/blob/0e395153306f34b3829d118b85bdd704136f2843/Erdos1/Resolutions/Erdos1_219usd_38h.lean#L2419"]
theorem erdos_1 : ¬ ∃ C > (0 : ℝ), ∀ (N : ℕ) (A : Finset ℕ) (_ : IsSumDistinctSet A N),
    N ≠ 0 → C * 2 ^ A.card < N := by
  -- EDITABLE BEGIN
  sorry
  -- EDITABLE END

end Erdos1
