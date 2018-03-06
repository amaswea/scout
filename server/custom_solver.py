import jsonpickle
import copy
import uuid
from z3 import *
import z3_helper
# What will we be solving for? 

# Steps
# 1. Design constructs initial design sketch
# 2. Designer creates initial set of constraints with relationships 
# 3. Solve


# What are the constraints? 
# Related Groups
# Related Collections
# Labels
# Captions
# Headers --> maybe
# Footers --> maybe
# Global -> No overlapping, no out of bounds

# What can we change just with labels relationship? 
# Labels 
# 	E1/G1 labels E2/G2
#   Element or group 1 labels element or group 2
#   Positions of the label: Top-Left, Center, Top-Right, Left
# 	Proximity of the label: GLOBAL value --> we should get this from somewhere

# Elements - N elements 
# Variables: X, Y, Width, Height, Position of the label (top-left, center, top-right,  left)
# The canvas
# - The overall layout canvas is an element that has constraints on alignment (left, center, right)
# Variables: Alignment (l,c,r)
# Arrangement: Vertical 
# Order unimportant -- Need to generate all of the possible orders  


# What positions make sense? 
	# The element is aligned to other elements on the page 
	# Or aligned globally (Left, Center, Right) or vertical position 

# Just one element (no changing size)
# Variables: X, Y
# Canvas Variables: Alignment, Justification
# Alignment values: Left, Center, Right
# Justification values: Top, Bottom, Center 


# With the label
# Variables for label placement: Left, Top-Left, Top-center, top-right
# Variables for canvas: 
# - Alignment - left, center, right
# - Justification - top, center, bottom
# - Order - The relative order of the elements


GRID_CONSTANT = 5
GLOBAL_PROXIMITY = 5

def get_shape_x_domain(width): 
	domain = []
	beg = 0 
	while beg <= width: 
		domain.append(beg)
		beg += GRID_CONSTANT
	return domain

def get_shape_y_domain(height): 
	domain = []
	beg = 0
	while beg <= height: 
		domain.append(beg)
		beg += GRID_CONSTANT
	return domain

class Shape(object):
	def __init__(self, shape_id, width, height): 
		self.type = "leaf"
		self.shape_id = shape_id
		self.width = width 
		self.height = height
		self.x = Variable(shape_id, "x")
		self.y = Variable(shape_id, "y")

class ContainerShape(Shape): 
	def __init__(self, shape_id, width=0, height=0): 
		Shape.__init__(self, shape_id, width, height)
		self.type = "container"
		self.children = []
		self.arrangement = Variable(shape_id, "arrangement", ["vertical", "horizontal"])

		# Width and Height will be adjustable for container shapes since their contents can change arrangements
		self.width = Int(shape_id + "_width")
		self.height = Int(shape_id + "_height")

class CanvasShape(Shape):
	def __init__(self, shape_id, width, height): 
		Shape.__init__(self, shape_id, width, height)
		self.children = []
		self.type = "canvas"
		self.alignment = Variable("canvas", "alignment", ["left", "right"])
		self.justification = Variable("canvas", "justification", ["top", "bottom"])
		self.arrangement = Variable("canvas", "arrangement", ["vertical", "horizontal"])
		self.orig_x = 0
		self.orig_y = 0

	def add_child(self, child): 
		self.children.append(child)

	def add_children(self, children): 
		self.children.extend(children)

class Variable(object): 
	def __init__(self, shape_id, name, domain=[]): 
		self.shape_id = shape_id
		self.name = name
		self.assigned = None
		self.domain = domain

		# Z3 Variable for testing (??)
		self.z3 = Int(shape_id + "_" + name)

	def domain(self, domain): 
		self.domain = domain

	def assign(self, value): 
		self.assigned = value

class Solution(object): 
	def __init__(self): 
		self.variables = []

	def add_assigned_variable(self, variable): 
		self.variables.append(variable)

	def convert_to_json(self, elements, shapes, model): 
		sln = dict()
		for e_index in range(0, len(elements)):  
			element = elements[e_index]
			shape = [shp for shp in shapes if shp.shape_id == element["name"]][0]

			f_x = model[shape.x.z3]
			f_y = model[shape.y.z3]
			adj_x = f_x.as_string()
			adj_y = f_y.as_string()
			adj_x = int(adj_x)
			adj_y = int(adj_y)

			# Copy the solved info back into the JSON shape
			element["location"]["x"] = adj_x
			element["location"]["y"] = adj_y

		new_elements = copy.deepcopy(elements);
		sln["elements"] = new_elements
		sln["id"] = uuid.uuid4().hex

		return sln

class Solver(object): 
	def __init__(self, elements, canvas_width, canvas_height): 
		self.solutions = [] # Initialize the variables somewhere
		self.unassigned = []
		self.elements = elements
		self.canvas_width = canvas_width
		self.canvas_height = canvas_height
		self.shapes, self.root = self.init_shapes(canvas_width, canvas_height)

		# Canvas contains all the elements as direct children for now
		self.canvas_shape = CanvasShape("canvas", canvas_width, canvas_height)	
		self.canvas_shape.add_children(self.root)
		self.variables = self.init_variables()

		# Construct the solver instance we will use for Z3
		self.solver = z3.Solver()
		self.solver_helper = z3_helper.Z3Helper(self.solver, canvas_width, canvas_height)
		self.init_domains()

		# To Do : Move elswhere
		self.init_container_constraints(self.canvas_shape)
		for shape in self.shapes: 
			if shape.type == "container": 
				self.init_container_constraints(shape)

	def init_shapes(self, canvas_width, canvas_height): 
		shapes = []
		root = []

		# Root will contain the root  level shapes (just below the canvas)
		for element in self.elements: 
			element_shape = Shape(element["name"], element["size"]["width"], element["size"]["height"])
			shapes.append(element_shape)
			root.append(element_shape)

		for element in self.elements: 
			element_name = element["name"]
			if "labels" in element: 
				# Find the shape & the corresponding labeled shape
				# TODO: Find better way to do this (using dictionary)
				label_shape = [shp for shp in root if shp.shape_id == element_name]
				labeled_shape = [shp for shp in root if shp.shape_id == element["labels"]]
				label_shape = label_shape[0]
				labeled_shape = labeled_shape[0]

				# Make a container for them to go into 
				container_id = uuid.uuid4().hex
				container_shape = ContainerShape(container_id)
				container_shape.children.append(label_shape)
				container_shape.children.append(labeled_shape)
				root.append(container_shape) 
				shapes.append(container_shape)

				# Remove the entries from the dictionary 
				root.remove(label_shape)
				root.remove(labeled_shape)

		# Shapes left in the dictionary are at the root level 
		return shapes, root

	# initialize domains
	def init_domains(self): 
		for shape in self.shapes: 
			# x_size = len(shape.x.domain)
			# y_size = len(shape.y.domain)
			self.solver.add(shape.x.z3 >= 0)
			self.solver.add((shape.x.z3 + shape.width) <= self.canvas_width)
			self.solver.add(shape.y.z3 >= 0)
			self.solver.add((shape.y.z3 + shape.height) <= self.canvas_height)

	def init_variables(self): 
		variables = []
		variables.append(self.canvas_shape.arrangement)
		variables.append(self.canvas_shape.alignment)
		variables.append(self.canvas_shape.justification)

		for child in self.root: 
			if child.type == "container" and len(child.children): 
				variables.append(child.arrangement)
		# Later: Justification and alignment 
		return variables

	# Intialize constraints on the containers for arrangment, ordering, justification, and alignment
	def init_container_constraints(self, container): 
		# Arrangment
		v_index = container.arrangement.domain.index("vertical")
		is_vertical = container.arrangement.z3 == v_index
		vertical_pairs = []
		horizontal_pairs = []
		child_widths = GLOBAL_PROXIMITY
		child_heights = GLOBAL_PROXIMITY
		child_shapes = container.children
		if len(child_shapes) > 0: 
			for s_index in range(0, len(child_shapes)-1): 
				shape1 = child_shapes[s_index]
				shape2 = child_shapes[s_index+1]
				vertical_pair_y = (shape1.y.z3 + shape1.height + GLOBAL_PROXIMITY) == shape2.y.z3 
				vertical_pair_x = (shape1.x.z3 == shape2.x.z3)
				vertical_pairs.append(vertical_pair_x)
				vertical_pairs.append(vertical_pair_y)
				horizontal_pair_x = (shape1.x.z3 + shape1.width + GLOBAL_PROXIMITY) == shape2.x.z3
				horizontal_pair_y = (shape1.y.z3 == shape2.y.z3)
				horizontal_pairs.append(horizontal_pair_x)
				horizontal_pairs.append(horizontal_pair_y)

			# Sum up the widths and heights
			max_width = -1 
			max_height = -1
			for child in child_shapes: 
				child_widths += child.width + GLOBAL_PROXIMITY
				child_heights += child.height + GLOBAL_PROXIMITY

				# if max_width == -1 or child.width > max_width: 
				# 	max_width = child.width 

				# if max_height == -1 or child.height > max_height: 
				# 	max_height = child.height

			vertical_arrange = And(vertical_pairs)
			horizontal_arrange = And(horizontal_pairs)
			self.solver.add(If(is_vertical, vertical_arrange, horizontal_arrange))

			if container.type == "container": 
				# Set the width and height of the container based on the arrangement  
				self.solver.add(If(is_vertical, container.height == child_heights, container.width == child_widths))

			# Alignment & Justification
			# Questions to resolve
			# Group that sizes to its content vs available spaace
			# For groups that are sizing to their contents, alignment and justification dont' make sense
			# Just restricting to the canvas for now, refactor later
			if container.type == "canvas": 
				first_shape = child_shapes[0]
				last_shape = child_shapes[len(child_shapes)-1]

				# The X,Y positions of the canvas are not adjustable
				if container.shape_id == "canvas": 
					self.solver.add(container.x.z3 == container.orig_x)
					self.solver.add(container.y.z3 == container.orig_y)

				l_index = container.alignment.domain.index("left")
				# c_index = container.alignment.domain.index("center")
				is_left = container.alignment.z3 == l_index
				# is_center = container.alignment.z3 == c_index

				# The first shape should be aligned to the left edge of the container
				left_aligned = first_shape.x.z3 == container.x.z3
				right_aligned = (last_shape.x.z3 + last_shape.width) == (container.x.z3 + container.width)

				# Center aligned
				self.solver.add(If(is_left, left_aligned, right_aligned))

				# Justification 
				t_index = container.justification.domain.index("top")
				is_top = container.justification.z3 == t_index
				top_justified = first_shape.y.z3 == container.y.z3
				bottom_justified = (last_shape.y.z3 + last_shape.height) == (container.y.z3 + container.height)
				self.solver.add(If(is_top, top_justified, bottom_justified))


	# def init_global_constraints():
	# 	# Stay in bounds of the canvas
	# 	for shape in self.shapes: 
	# 		self.solver_helper.add_bounds_constraints(shape) 

	def solve(self): 
		self.unassigned = copy.copy(self.variables)
		self.branch_and_bound()
		return self.solutions

	def select_next_variable(self):
		return self.unassigned.pop()

	def restore_variable(self, variable): 
		variable.assigned = None
		self.unassigned.append(variable)

	def encode_assigned_variables(self): 
		for variable in self.variables: 
			self.solver.add(variable.z3 == variable.assigned)

	def branch_and_bound(self, state=Solution()): 
		# Dumb this down so we are not optimizing for the cost right now
		# State keeps track of the variables assigned so far
		if len(self.unassigned) == 0: 
			# Create a new stack context so we can remove the assignments after solving
			self.solver.push()
			self.encode_assigned_variables()

			# Ask the solver for a solution to the X,Y location varibles
			constraints = self.solver.sexpr()
			result = self.solver.check();


			# Remove the stack context from the assignment
			self.solver.pop()

			# obj = self.solver.objectives()
			if str(result) == 'sat': 
				# Find one solution for now
				model = self.solver.model()
				# Keep the solution 
				sln = state.convert_to_json(self.elements, self.shapes, model)
				self.solutions.append(sln)
				return 
			else: 
				print("not sat... uh oh")
		else: 
			# Selects the next variable to assign
			next_var = self.select_next_variable()
			state.add_assigned_variable(next_var)
			for val_index in range(0, len(next_var.domain)): 
				next_var.assigned = val_index
				self.branch_and_bound(state)

			# Then unassign the value
			self.restore_variable(next_var)
		return 

# if __name__ == "__main__":
# 	# with open('specification/with_labels.json') as data_file:
# 	#     shapes = json.load(data_file)
# 	# shapes = dict() 
# 	# child1 = Shape("child1", 50, 50)
# 	# shapes["child1"] = child1
# 	# canvas = Shape("canvas", 375, 667)
# 	# canvas.add_child(child1)
# 	# shapes["canvas"] = canvas

# 	# # Create some variables
# 	# var1 = Variable("canvas", "alignment", ["left", "right", "center"])
# 	# var2 = Variable("canvas", "justification", ["top", "bottom", "center"])
# 	# variables = []
# 	# variables.append(var1)
# 	# variables.append(var2)
# 	# solver = Solver(shapes)
# 	# solver.solve(variables)

# 	# for shape_key, shape in shapes.items(): 
# 	# 	print("-----------------")
# 	# 	print(shape.shape_id)
# 	# 	print(shape.x, shape.y, shape.width, shape.height)

# 	for sln in solver.solutions: 
# 		print(sln)








