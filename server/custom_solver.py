import jsonpickle
import copy
import uuid
from z3 import *
import z3_helper
import shapes as shape_classes
import solver_helpers as sh
import time
import random
import constraint_builder

GRID_CONSTANT = 5
GLOBAL_PROXIMITY = 5
NUM_SOLUTIONS = 10
NUM_DIFFERENT = 5

class Solver(object): 
	def __init__(self, elements, solutions, canvas_width, canvas_height, relative_designs=None): 
		self.solutions = [] # Initialize the variables somewhere
		self.unassigned = []
		self.elements = elements
		self.previous_solutions = solutions
		self.canvas_width = canvas_width
		self.canvas_height = canvas_height
		self.relative_search = False
		self.shapes, self.root = self.build_shape_hierarchy()
		self.root = self.root[0]

		self.variables = self.init_variables()
		self.output_variables = self.init_output_variables()
		self.previous_solution = IntVector('PrevSolution', len(self.variables))
		self.variables_different = Int('VariablesDifferent')

		# Construct the solver instance we will use for Z3
		self.solver = z3.Solver()
		self.solver_helper = z3_helper.Z3Helper(self.solver, canvas_width, canvas_height)
		self.cb = constraint_builder.ConstraintBuilder(self.solver)
		self.init_domains()

		# Initialize the set of constraints on shapes and containers
		for shape in self.shapes.values(): 
			if shape.type == "canvas": 
				self.cb.init_canvas_constraints(shape)
			elif shape.type == "container": 
				self.cb.init_container_constraints(shape)

		# Initialize the previous solution constraints
		# self.cb.init_previous_solution_constraints(self.previous_solutions, self.shapes)

		# Initialize any relative design constraints, if given 
		# if "relative_design" in relative_designs: 
		# 	self.relative_search = True
		# 	relative_design_elements = relative_designs["relative_design"]
		# 	relative_design_action = relative_design["relative_action"]

		# 	if relative_design_action == "like": 
		# 		self.cb.init_relative_design_constraints(relative_design_elements)
		# 		# Set up constraints to get designs more like the relative design
		# 		# This means any returned solution should only have 1 variable different than the relative design

		# Timing variables to measure performance for various parts
		self.time_z3 = 0
		self.time_encoding = 0
		self.invalid_solutions = 0 # Used to keep track of the number of invalid solutions
		self.num_solutions = 0
		self.branches_pruned = 0
		self.z3_calls = 0

	def build_shape_hierarchy(self): 
		shapes = dict()
		root = self.construct_shape_hierarchy([self.elements], shapes)
		return shapes,root

	def process_children(self, element, children, elements): 
		new_children = []
		for child_id in children: 
			# Find the element with this id 
			child_element = [child for child in elements if child["name"] == child_id][0]
			new_children.append(child_element)

			# If it does not have any children of its own, remove it from the queue
			if "children" in child_element: 
				self.process_children(child_element, child_element["children"], elements)

			# then remove the element from the elements queue
			child_index = elements.index(child_element)
			elements.pop(child_index)

			child_element["processed"] = True

		element["children"] = new_children	

	def construct_shape_hierarchy(self, elements, shapes):
		shape_hierarchy = []
		for i in range(0, len(elements)): 
			element = elements[i]

			sub_hierarchy = None
			if "children" in element: 
				children = element["children"]
				sub_hierarchy = self.construct_shape_hierarchy(children, shapes)

			shape_object = None
			if element["type"] == "canvas": 
				shape_object = shape_classes.CanvasShape(element["name"], element)
				shapes[shape_object.shape_id] = shape_object
			elif element["type"] == "page":	
				shape_object = shape_classes.ContainerShape(element["name"], element)
				shapes[shape_object.shape_id] = shape_object
			elif element["type"] == "group" or element["type"] == "labelGroup":
				shape_object = shape_classes.ContainerShape(element["name"], element)
				shapes[shape_object.shape_id] = shape_object
			else:
				shape_object = shape_classes.LeafShape(element["name"], element)
				shapes[shape_object.shape_id] = shape_object

			if sub_hierarchy is not None: 
				shape_object.add_children(sub_hierarchy)

			shape_hierarchy.append(shape_object)

		return shape_hierarchy

	# initialize domains
	def init_domains(self):
		for shape in self.shapes.values():
			# x_size = len(shape.x.domain)
			# y_size = len(shape.y.domain)
			self.solver.add(shape.variables.x.z3 >= 0)
			self.solver.add((shape.variables.x.z3 + shape.width) <= self.canvas_width)
			self.solver.add(shape.variables.y.z3 >= 0)
			self.solver.add((shape.variables.y.z3 + shape.height) <= self.canvas_height)

	def init_variables(self):
		last = []
		first = []
		variables = []

		for shape in self.shapes.values():
			if shape.type == "container": 
				first.append(shape.variables.arrangement)
				last.append(shape.variables.alignment)
				last.append(shape.variables.proximity)
			
			if shape.type == "canvas":
				last.append(shape.variables.alignment)
				last.append(shape.variables.justification)
				last.append(shape.variables.margin)

		# More important variables are in first. putting them at the end of the list , they will get assigned first
		variables.extend(last)
		variables.extend(first)

		# Later: Justification and alignment
		return variables

	def init_output_variables(self):
		output_variables = []
		for shape in self.shapes.values(): 
			if shape.type != "container" and shape.type != "canvas": 
				output_variables.append(shape.variables.x)
				output_variables.append(shape.variables.y)
		return output_variables

	def compute_search_space(self):
		total = 1
		for variable in self.variables:
			total *= len(variable.domain)
		return total		

	# def init_global_constraints():
	# 	# Stay in bounds of the canvas
	# 	for shape in self.shapes:
	# 		self.solver_helper.add_bounds_constraints(shape)

	# This function just checks for satisfiability of the current set of constraints
	# Doesn't return any solutions back 
	def check(self):
		results = dict()

		# Encode the fixed constraints 
		for shape in self.shapes.values(): 
			self.cb.init_locks(shape)

		time_start = time.time()
		valid = self.z3_check(time_start)

		results["valid"] = valid

		# Check all of the previous solutions
		for solution in self.previous_solutions: 
			# Create a new stack context for the solver before we encode the fixed values for the solution
			self.solver.push() 

			# Look for any shapes that have been removed or added in this solution
			shapes_removed = []
			shapes_added = []
			elements = solution["elements"]
			for elementID in elements:
				if elementID not in self.shapes:
					shapes_removed.append(elementID)

			for shapeID in self.shapes:
				if shapeID not in elements:
					shapes_added.append(shapeID)

			if len(shapes_added) or len(shapes_removed):
				# If any shapes were added or removed from the canvas since this solution was retrieved
				# Mark the solution as invalid
				solution["valid"] = False

				# Send back the added and removed shapes to be used for highlighting inconsistencies in the constriants tree
				solution["added"] = shapes_added
				solution["removed"] = shapes_removed

				print("Shapes were added or removed. not resolving. ")
			else:
				# For this solution, fix the values of the variables to the solution values
				# Otherwise, check the solution for validity again
				# This encodes the values that should be fixed for this solution
				self.cb.init_solution_constraints(self.shapes, elements)

				start_time = time.time()
				result = self.z3_check(start_time)

				# update the valid state of the solution
				solution["valid"] = result

				if result:
					print("Solution could be found.")
				else:
					print("Solution could not be found.")

			self.solver.pop()

		time_end = time.time()
		total_time = time_end - time_start
		print("Total time to check satisfiability: " + str(total_time))
		results["solutions"] = self.previous_solutions
		return results

	def solve(self):
		# Initialize the set of fixed constraints on shapes and containers
		for shape in self.shapes.values(): 
			self.cb.init_locks(shape)
			
		# Initialize the constraints preventing previous solutions from re-occuring
		self.cb.init_previous_solution_constraints(self.previous_solutions, self.shapes)

		self.unassigned = copy.copy(self.variables)

		# For debugging how large the search space isd
		size = self.compute_search_space()
		print("Total search space size: " + str(size))

		start_time = time.time()

		# Z3 looping version
		# self.z3_solve(start_time, size)

		# Branch and bound regular 
		# self.branch_and_bound(start_time)

		# Branch and bound get one solution at a time
		self.branch_and_bound_n_solutions(start_time)

		end_time = time.time()
		print("number of solutions found: " + str(len(self.solutions)))
		print("number of invalid solutions: " + str(self.invalid_solutions))
		print("branches pruned: " + str(self.branches_pruned))
		print("Z3 time: " + str(self.time_z3))
		print("Z3 calls: " + str(self.z3_calls))
		print("Encoding time: " + str(self.time_encoding))
		print("Amount of time taken: " + str(end_time-start_time))

		if len(self.solutions):
			self.solutions.sort(key=lambda s: s["cost"])
			print("lowest cost: " + str(self.solutions[0]["cost"]))
			print("highest cost: " + str(self.solutions[len(self.solutions)-1]["cost"]))
		else:
			print("No solutions found.")
		return self.solutions

	def select_next_variable(self):
		return self.unassigned.pop()

	def select_next_variable_random(self): 
		# Select a random index to assign
		random_index = random.randint(0, len(self.unassigned)-1)
		return random_index, self.unassigned.pop(random_index)

	def restore_variable(self, variable, index):
		variable.assigned = None
		self.unassigned.insert(index, variable)

	def get_randomized_domain(self, variable):
		randomized_domain = variable.domain[0:len(variable.domain)]
		random.shuffle(randomized_domain)
		return randomized_domain

	def encode_assigned_variables(self):
		variable_equals_assigned = []
		for variable in self.variables:
			variable_equals_assigned.append(variable.z3 == variable.assigned)
		self.solver.add(And(variable_equals_assigned))

	def encode_assigned_variable(self, variable):
		time_encoding_start = time.time()
		if variable.name == "proximity" or variable.name == "margin":
			prox_value = variable.domain[variable.assigned]
			self.solver.add(variable.z3 == prox_value)
		else:
			self.solver.add(variable.z3 == variable.assigned)

		time_encoding_end = time.time()
		self.time_encoding += (time_encoding_end - time_encoding_start)

	# Computes the number of variables that are different than the previous solution
	def num_variables_different(self): 
		vars_diff = 0
		for var_i in range(0, len(self.variables)): 
			variable = self.variables[var_i]
			vars_diff += If(variable.z3 != self.previous_solution[var_i], 1, 0)
		return vars_diff

	def encode_previous_solution_from_model(self, model): 
		# The next solution cannot be the exact same outputs as the previous assignment
		# It may be possible for multiple solutions to have the same outputs (exact x,y coordinates for all shapes)
		# So to restrict this, we encode the X,Y positions in the clauses to prevent these solutions
		all_values = []
		for v_i in range(0, len(self.output_variables)): 
			variable = self.output_variables[v_i]
			variable_value = model[variable.z3]
			variable_value = variable_value.as_string() 
			variable_value = int(variable_value)
			all_values.append(variable.z3 == variable_value)

		self.solver.add(Not(And(all_values)))	

	def encode_constraints_for_model(self, model): 
		# Pop the previous 
		if self.num_solutions > 1: 
			# Remove the previous stack context
			# Pop the stack context before adding the set of constraints to prevent the 
			# Previous solution model from appearing again
			self.solver.pop()

		# The next solution cannot be the exact same set of assignments as the current solution
		# These are cumulative
		self.encode_previous_solution_from_model(model)
			
		# Build the vector to store the previous solution
		previous_solution_values = []
		for v_i in range(0, len(self.variables)): 
			variable = self.variables[v_i]
			variable_value = model[variable.z3]
			variable_value = variable_value.as_string() 
			variable_value = int(variable_value)
			previous_solution_values.append(self.previous_solution[v_i] == variable_value)

		if self.num_solutions > 0: 
			self.solver.push()
			
			# Add the previous solution values for the cost function
			self.solver.add(previous_solution_values) 

			# New solutions must be at least NUM_DIFFERENT variable changes away from 
			# the previous solution
			self.solver.add(self.variables_different == self.num_variables_different())

			half = math.floor(len(self.variables)/2)
			self.solver.add(self.variables_different >= half)

	def print_solution_from_model(self, model): 
		print("------------Solution-------------")
		for variable in self.variables: 
			# Get the value of the variable out of the model 
			variable_value = model[variable.z3]
			variable_value = variable_value.as_string()
			variable_value = int(variable_value)
			print(variable.shape_id)
			print(variable.name)
			print(variable_value)

	def print_solution(self):
		print("------------Solution------------")
		for variable in self.variables:
			print(variable.shape_id)
			print(str(variable.domain[variable.assigned]))

	def print_partial_solution(self):
		for variable in self.variables:
			if variable.assigned is not None:
				print(variable.shape_id)
				print(str(variable.domain[variable.assigned]))


	def z3_check(self, time_start): 
		time_z3_start = time.time()
		result = self.solver.check()
		unsat_core = self.solver.unsat_core()
		time_z3_end = time.time()
		time_z3_total = time_z3_end - time_z3_start
		self.time_z3 += time_z3_total
		if str(result) == 'sat': 
			return True
		else: 
			return False

	# Loop and solve until num solutions is reached
	def z3_solve(self, time_start, search_space_size, state=sh.Solution()):
		print("num variables " + str(len(self.variables)))
		while self.num_solutions < NUM_SOLUTIONS and (self.num_solutions + self.invalid_solutions) < search_space_size: 
			# print("valid: " + str(self.num_solutions))
			# Call to Z3 
			time_z3_start = time.time()
			result = self.solver.check();
			self.z3_calls += 1
			time_z3_end = time.time()
			time_z3_total = time_z3_end - time_z3_start
			self.time_z3 += time_z3_total
			if str(result) == 'sat': 
				self.num_solutions += 1

				# Find one solution for now
				time_z3_start = time.time()
				model = self.solver.model()
				time_z3_start = time.time()
				time_z3_total = time_z3_end - time_z3_start
				self.time_z3 += time_z3_total

				sln = state.convert_to_json(self.shapes, model)
				self.solutions.append(sln)

				# Encode a conjunction into the solver
				if not self.relative_search: 
					# Encodes the previous solution plus a cost function enforce the number of variables to be different by a certain amount each time. 
					self.encode_constraints_for_model(model)
				else:
					# Encodes only the previous solution to prevent that solution from appearing again 
					self.encode_previous_solution_from_model(model)

				# self.print_solution_from_model(model)

				if len(self.solutions) == NUM_SOLUTIONS:
					time_end = time.time()
					total_time = time_end - time_start
					print("Total time to " + str(NUM_SOLUTIONS) + ": " + str(total_time))
			else: 
				self.invalid_solutions += 1

	def branch_and_bound(self, time_start, state=sh.Solution()):
		if self.num_solutions >= NUM_SOLUTIONS:
			return

		if len(self.unassigned) == 0:
			# Ask the solver for a solution to the X,Y location varibles
			constraints = self.solver.sexpr()
			time_z3_start = time.time()
			result = self.solver.check();
			self.z3_calls += 1
			time_z3_end = time.time()
			time_z3_total = time_z3_end - time_z3_start
			self.time_z3 += time_z3_total
			unsat_core = self.solver.unsat_core()
			self.print_solution()

			if str(result) == 'sat':
				# print("------Valid solution------")
				self.num_solutions += 1

				# Find one solution for now
				time_z3_start = time.time()
				model = self.solver.model()
				time_z3_start = time.time()
				time_z3_total = time_z3_end - time_z3_start
				self.time_z3 += time_z3_total

				# Keep the solution & convert to json
				sln = state.convert_to_json(self.shapes, model)
				self.solutions.append(sln)
				if len(self.solutions) == NUM_SOLUTIONS:
					time_end = time.time()
					total_time = time_end - time_start
					print("Total time to " + str(NUM_SOLUTIONS) + ": " + str(total_time))
				return
			else:
				self.invalid_solutions += 1
				# self.print_solution()
		else:
			# Selects the next variable to assign
			var_i, next_var = self.select_next_variable()
			state.add_assigned_variable(next_var)

			# Randomize the order in which we iterate through the domain
			# random_domain = self.get_randomized_domain(next_var)
			for val_index in range(0, len(next_var.domain)):
				next_var.assigned = val_index

				# Creates a new stack context for the variable assignment
				self.solver.push()

				# Set the value of the variable to fixed in the solver
				self.encode_assigned_variable(next_var)

				# GGet a solution
				time_z3_start = time.time()
				result = self.solver.check()
				self.z3_calls += 1
				time_z3_end = time.time()
				time_z3_total = time_z3_end - time_z3_start
				self.time_z3 += time_z3_total

				# Only branch if the result so far is satisfiable
				if str(result) == 'sat':
					self.branch_and_bound(time_start, state)
				else: 
					# print("pruning branch: ")
					# self.print_partial_solution()
					self.branches_pruned+=1

				# Remove the stack context after the branch for this assignment has been explored
				self.solver.pop()

			# Then unassign the value
			self.restore_variable(next_var, var_i)
		return 

	def branch_and_bound_n_solutions(self, time_start): 
		while self.num_solutions < NUM_SOLUTIONS:
			state = sh.Solution()
			sln = self.branch_and_bound_random(time_start, state)
			if sln is not None: 
				self.solutions.append(sln)
				self.num_solutions += 1
			else: 
				print("No more solutions could be found.")
				break 

		time_end = time.time()
		total_time = time_end - time_start
		print("Total time to " + str(NUM_SOLUTIONS) + ": " + str(total_time))

	def restore_state(self): 
		# Unassign and reset the variables
		for variable in self.variables: 
			variable.assigned = None

		self.unassigned = copy.copy(self.variables)

		# Restore the stack context for the solver
		for i in range(0, len(self.variables)):
			self.solver.pop()

	def branch_and_bound_random(self, time_start, state):
		if len(self.unassigned) == 0:
			time_z3_start = time.time()
			result = self.solver.check()
			constraints = self.solver.sexpr()
			unsat_core = self.solver.unsat_core()
			self.z3_calls += 1
			time_z3_end = time.time()
			time_z3_total = time_z3_end - time_z3_start
			self.time_z3 += time_z3_total

			if str(result) == 'sat':
				# Find one solution for now
				time_z3_start = time.time()
				model = self.solver.model()
				time_z3_start = time.time()
				time_z3_total = time_z3_end - time_z3_start
				self.time_z3 += time_z3_total

				# Keep the solution & convert to json
				self.print_solution()

				sln = state.convert_to_json(self.shapes, model)
				self.restore_state()

				# Encode the previous solution outputs into the model so we don't produce it again in the next iteration
				self.encode_previous_solution_from_model(model)
				return sln
			else:
				self.invalid_solutions += 1
				# self.print_solution()
		else:
			# Selects the next variable to assign
			var_i, next_var = self.select_next_variable_random()
			state.add_assigned_variable(next_var)

			# Randomize the order in which we iterate through the domain
			random_domain = self.get_randomized_domain(next_var)
			for val_index in range(0, len(random_domain)):
				dom_value = random_domain[val_index]
				in_domain_index = next_var.domain.index(dom_value)
				next_var.assigned = in_domain_index

				# Creates a new stack context for the variable assignment
				self.solver.push()

				# Set the value of the variable to fixed in the solvfer
				self.encode_assigned_variable(next_var)

				# GGet a solution
				time_z3_start = time.time()
				result = self.solver.check()
				unsat_core = self.solver.unsat_core()
				self.z3_calls += 1
				time_z3_end = time.time()
				time_z3_total = time_z3_end - time_z3_start
				self.time_z3 += time_z3_total

				# Only branch if the result so far is satisfiable
				if str(result) == 'sat':
					sln = self.branch_and_bound_random(time_start, state)
					if sln is not None: 
						return sln
				else: 
					# print("pruning branch: ")
					# self.print_partial_solution()
					self.branches_pruned+=1

				# Remove the stack context after the branch for this assignment has been explored
				self.solver.pop()

			# Then unassign the value
			self.restore_variable(next_var, var_i)
		return 









