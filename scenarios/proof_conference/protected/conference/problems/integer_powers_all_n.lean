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

/-! # Mathoverflow 17560


*Reference:* [mathoverflow/17560](https://mathoverflow.net/questions/17560)
asked by user [Alon-Amit](https://mathoverflow.net/users/25/alon-amit)
-/

@[expose] public section

namespace Mathoverflow17560

-- EDITABLE BEGIN
-- EDITABLE END

/--
If for each natural number $n$ the number $n^x$ is an integer then $x$ must also be an integer.
-/
@[category textbook, AMS 11 13]
theorem mathoverflow_17560.variants.all_nats {x : ℝ} (hx : ∀ n : ℕ, ∃ m : ℕ, (n : ℝ) ^ x = m) :
    ∃ m : ℕ, x = m := by
  -- EDITABLE BEGIN
  sorry
  -- EDITABLE END

end Mathoverflow17560
