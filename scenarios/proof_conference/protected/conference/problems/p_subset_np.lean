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
# Conjectures in Complexity Theory

This file contains formal statements of some of the main open conjectures
in complexity theory, including

- the P vs NP problem
- the NP vs coNP problem
- the P vs BPP problem

*References:*
- [Wikipedia](https://en.wikipedia.org/wiki/P_versus_NP_problem)
- [The Clay Institute](https://www.claymath.org/millennium/p-vs-np/)
-/

@[expose] public section

namespace ComplexityTheory

-- EDITABLE BEGIN
-- EDITABLE END

/--
The theorem that P is a subset of NP.

This can be proven by observing that for any language in P,
we can construct a verifier that ignores the witness and simply runs the poly-time decider for the
language.
-/
@[category textbook, AMS 68, formal_proof using lean4 at
  "https://github.com/AItoBit/p-subset-np/blob/beaeee15c37af6efac518426e117861c00ff3acc/PSubsetNP.lean#L358"]
theorem P_subset_NP :
    P ⊆ NP := by
  -- EDITABLE BEGIN
  sorry
  -- EDITABLE END

end ComplexityTheory
