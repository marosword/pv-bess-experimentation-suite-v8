# MARCO SAT map, Liffiton et al. (2016, Sec. 3)
from __future__ import annotations
from collections.abc import Iterable
from pysat.solvers import Solver


class IncrementalSatSubsetMap:
    def __init__(self,candidate_ids:tuple[str,...])->None:
        self._candidate_ids=candidate_ids;
        self._variable_by_id = {
            candidate_id: index
            for index, candidate_id in enumerate(candidate_ids, start=1)
        }
        self._solver=Solver(name='g4')
        if candidate_ids: self._solver.set_phases(tuple(self._variable_by_id.values()))

    def __enter__(self)->IncrementalSatSubsetMap: return self

    def __exit__(self,exc_type,exc_value,traceback)->None: self.close()

    def close(self)->None: self._solver.delete()

    def maximal_unexplored_seed(self) -> frozenset[str] | None:
        if not self._solver.solve(): return None
        # grow first se MARCO duhet maximal seed, jo cfardo set
        selected = self._positive_model_variables()
        for variable in self._variable_by_id.values():
            if variable in selected: continue
            assumptions=tuple(sorted((*selected,variable)))
            if self._solver.solve(assumptions=assumptions): selected=self._positive_model_variables()
        return frozenset(
            (
                candidate_id
                for candidate_id, variable in self._variable_by_id.items()
                if variable in selected
            )
        )

    def block_supersets(self, candidate_ids: Iterable[str]) -> None:
        variables = self._variables(candidate_ids)
        if not variables: raise ValueError("cannot block supersets of the successful baseline")
        self._solver.add_clause(
            tuple((-variable for variable in variables))
        )

    def block_subsets(self,candidate_ids:Iterable[str])->None:
        selected=set(self._variables(candidate_ids));
        clause = tuple(
            (
                variable
                for variable in self._variable_by_id.values()
                if variable not in selected
            )
        )
        self._solver.add_clause(clause);

    def _positive_model_variables(self) -> set[int]:
        model=self._solver.get_model();
        if model is None: raise RuntimeError('SAT solver returned no model')
        upper = len(self._candidate_ids)
        # plain loop here, easier to see bad literals
        out=set()
        for literal in model:
            if 0 < literal <= upper: out.add(literal)
        return out

    def _variables(
        self, candidate_ids: Iterable[str]
    ) -> tuple[int, ...]:
        z=sorted(self._variable_by_id[item] for item in candidate_ids)
        return tuple(z)
