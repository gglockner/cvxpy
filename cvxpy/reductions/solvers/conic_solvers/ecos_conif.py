"""
Copyright 2013 Steven Diamond, 2017 Robin Verschueren

This file is part of CVXPY.

CVXPY is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

CVXPY is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with CVXPY.  If not, see <http://www.gnu.org/licenses/>.
"""

import numpy as np

import cvxpy.settings as s
from cvxpy.constraints import SOC, ExpCone, NonPos, Zero
from cvxpy.problems.objective import Minimize
from cvxpy.reductions.solution import failure_solution, Solution
from cvxpy.reductions.solvers.solver import group_constraints

from .conic_solver import ConicSolver


class ECOS(ConicSolver):
    """An interface for the ECOS solver.
    """

    # Solver capabilities.
    MIP_CAPABLE = False
    SUPPORTED_CONSTRAINTS = ConicSolver.SUPPORTED_CONSTRAINTS + [SOC, ExpCone]

    # EXITCODES from ECOS
    # ECOS_OPTIMAL  (0)   Problem solved to optimality
    # ECOS_PINF     (1)   Found certificate of primal infeasibility
    # ECOS_DINF     (2)   Found certificate of dual infeasibility
    # ECOS_INACC_OFFSET (10)  Offset exitflag at inaccurate results
    # ECOS_MAXIT    (-1)  Maximum number of iterations reached
    # ECOS_NUMERICS (-2)  Search direction unreliable
    # ECOS_OUTCONE  (-3)  s or z got outside the cone, numerics?
    # ECOS_SIGINT   (-4)  solver interrupted by a signal/ctrl-c
    # ECOS_FATAL    (-7)  Unknown problem in solver

    # Map of ECOS status to CVXPY status.
    STATUS_MAP = {0: s.OPTIMAL,
                  1: s.INFEASIBLE,
                  2: s.UNBOUNDED,
                  10: s.OPTIMAL_INACCURATE,
                  11: s.INFEASIBLE_INACCURATE,
                  12: s.UNBOUNDED_INACCURATE,
                  -1: s.SOLVER_ERROR,
                  -2: s.SOLVER_ERROR,
                  -3: s.SOLVER_ERROR,
                  -4: s.SOLVER_ERROR,
                  -7: s.SOLVER_ERROR}

    # Order of exponential cone arguments for solver.
    EXP_CONE_ORDER = [0, 2, 1]

    def import_solver(self):
        """Imports the solver.
        """
        import ecos
        ecos  # For flake8

    def name(self):
        """The name of the solver.
        """
        return s.ECOS

    def apply(self, problem):
        """Returns a new problem and data for inverting the new solution.

        Returns
        -------
        tuple
            (dict of arguments needed for the solver, inverse data)
        """
        data = {}
        inv_data = {self.VAR_ID: problem.variables()[0].id}
        data[s.C], data[s.OFFSET] = ConicSolver.get_coeff_offset(
            problem.objective.args[0])
        data[s.C] = data[s.C].ravel()
        inv_data[s.OFFSET] = data[s.OFFSET][0]

        constr_map = group_constraints(problem.constraints)
        inv_data[self.EQ_CONSTR] = constr_map[Zero]
        data[s.A], data[s.B] = self.group_coeff_offset(constr_map[Zero],
            ECOS.EXP_CONE_ORDER)

        # Order and group nonlinear constraints.
        data[s.DIMS] = {}
        data[s.DIMS]['l'] = sum([np.prod(c.size) for c in constr_map[NonPos]])
        data[s.DIMS]['q'] = [sz for c in constr_map[SOC]
                                  for sz in c.cone_sizes()]
        data[s.DIMS]['e'] = sum([c.num_cones() for c in constr_map[ExpCone]])

        neq_constr = constr_map[NonPos] + constr_map[SOC] + constr_map[ExpCone]
        inv_data[self.NEQ_CONSTR] = neq_constr
        data[s.G], data[s.H] = self.group_coeff_offset(neq_constr,
            ECOS.EXP_CONE_ORDER)

        return data, inv_data

    def invert(self, solution, inverse_data):
        """Returns solution to original problem, given inverse_data.
        """
        status = self.STATUS_MAP[solution['info']['exitFlag']]

        # Timing data
        attr = {}
        attr[s.SOLVE_TIME] = solution["info"]["timing"]["tsolve"]
        attr[s.SETUP_TIME] = solution["info"]["timing"]["tsetup"]
        attr[s.NUM_ITERS] = solution["info"]["iter"]

        if status in s.SOLUTION_PRESENT:
            primal_val = solution['info']['pcost']
            opt_val = primal_val + inverse_data[s.OFFSET]
            primal_vars = {inverse_data[self.VAR_ID]: solution['x']}
            eq_dual = ConicSolver.get_dual_values(solution['y'],
                inverse_data[self.EQ_CONSTR])
            leq_dual = ConicSolver.get_dual_values(solution['z'],
                inverse_data[self.NEQ_CONSTR])
            eq_dual.update(leq_dual)
            dual_vars = eq_dual
            return Solution(status, opt_val, primal_vars, dual_vars, attr)
        else:
            return failure_solution(status)

    def solve_via_data(self, data, warm_start, verbose, solver_opts):
        import ecos
        solution = ecos.solve(data[s.C], data[s.G], data[s.H],
                              data[s.DIMS], data[s.A], data[s.B],
                              verbose=verbose,
                              **solver_opts)
        return solution
