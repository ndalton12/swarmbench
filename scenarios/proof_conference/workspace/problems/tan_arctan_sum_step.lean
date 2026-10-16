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
# Integer values of $\tan(\arctan 1 + \arctan 2 + \cdots + \arctan n)$

*References:*
- [arxiv/2607.05739](https://arxiv.org/abs/2607.05739)
  **Integer values of $\tan(\arctan 1+\arctan 2+\cdots+\arctan n)$ are rare** by *Ken Ono*
- [AMM08] T. Amdeberhan, L. A. Medina, and V. H. Moll, *Arithmetical properties of a sequence
  arising from an arctangent sum*, J. Number Theory 128 (2008), no. 6, 1807-1846.
- [TanArctan](https://github.com/AxiomMath/TanArctan), a Lean formalisation of the three
  results of [Ono26], MIT licensed. Its `P`, `A`, `B` and `x` are the definitions used
  here.
-/

@[expose] public section

open Finset

namespace Arxiv.«2607.05739»

/-- $Z_n = \prod_{k=1}^n (1 + ik)$, in the Gaussian integers. -/
def gaussProd (n : ℕ) : GaussianInt := ∏ k ∈ Finset.Icc 1 n, (⟨1, (k : ℤ)⟩ : GaussianInt)

/-- $A_n = \operatorname{Re} Z_n$. -/
def A (n : ℕ) : ℤ := (gaussProd n).re

/-- $B_n = \operatorname{Im} Z_n$. -/
def B (n : ℕ) : ℤ := (gaussProd n).im

/-- $x_n = \tan\left(\sum_{k=1}^n \arctan k\right) = B_n / A_n$. -/
noncomputable def x (n : ℕ) : ℚ := (B n : ℚ) / (A n : ℚ)

/-- $x_n$ takes an integer value.

Stated as $A_n \mid B_n$ rather than as `∃ m : ℤ, x n = m`, so that it still says the right
thing if $A_n$ were ever $0$. There $x_n$ is a pole of the tangent rather than an integer, but
`(B n : ℚ) / 0` is `0` in Lean and would count as one. The two agree whenever $A_n \neq 0$,
which holds for every $n \leq 3000$. -/
def IsIntegerValue (n : ℕ) : Prop := A n ∣ B n

instance (n : ℕ) : Decidable (IsIntegerValue n) := by unfold IsIntegerValue; infer_instance

-- EDITABLE BEGIN
-- EDITABLE END

/-- $x_n$ satisfies $x_1 = 1$ and $x_n = \dfrac{x_{n-1} + n}{1 - n x_{n-1}}$, which is the
tangent addition formula. -/
@[category textbook, AMS 11]
theorem x_succ (n : ℕ) (hn : 1 ≤ n) :
    x (n + 1) = (x n + (n + 1)) / (1 - (n + 1) * x n) := by
  -- EDITABLE BEGIN
  sorry
  -- EDITABLE END

end Arxiv.«2607.05739»
