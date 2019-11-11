__all__ = ['CallTree', 'CallInfo', 'Tracer', 'TracerProxy', 'clear_call_tree', 'print_call_tree', 'trace_calls', 'tracer', 'trace_method_calls', 'use_tracer']

import sys
from copy import deepcopy 
from functools import wraps

class CallTree:
	def __init__(self, children=None, value=None, parent=None):
		self.value = value
		self.parent_node = parent
		self.child_list = []
		
		if children is not None:
			for child in children:
				if isinstance(child, CallTree):
					child = self.__class__(child.children(), child.value, self)
					self.add_child_node(child)
				elif hasattr(child, '__iter__'):
					child = self.__class__(children=child, parent=self)
					self.add_child_node(child)
				else:
					self.add_child(child)
	
	def parent(self):
		return self.parent_node
	def children(self):
		return self.child_list
	def root_node(self):
		a = self
		while a.parent() is not None:
			a = a.parent()
		return a
	def height(self):
		h = 0
		a = self
		while a.parent() is not None:
			a = self.parent()
			h += 1
		return h
	def ancestors(self):
		a = self
		ancestors = [self]
		while a.parent() is not None:
			a = a.parent()
			ancestors.append(a)
		return ancestors
	def descendants(self):
		descendants = [self]
		for c in self.children():
			descendants.extend(c.descendants())
		return descendants
	def values(self):
		return [ node.value for node in self.descendants() if node.value is not None ]
	def is_leaf_node(self):
		return len(self.children()) == 0
	def leaf_nodes(self):
		if self.is_leaf_node():
			leaf_nodes = [self]
		else:
			leaf_nodes = []
			for c in self.children():
				leaf_nodes.extend(c.leaf_nodes())
		return leaf_nodes
	
	def filter(self, predicate):
		def find_shallowest_descendants(root,node):
			if node is not root and predicate(node):
				return [node]
			else:
				result = []
				for c in node.children():
					result.extend(find_shallowest_descendants(root,c))
				return result
		new_root = self.__class__(value=self.value)
		for c in find_shallowest_descendants(self,self):
			new_child = c.filter(predicate)
			new_child.parent_node = new_root
			new_root.add_child_node(new_child)
		return new_root
	def for_function(self, f):
		filter_predicate = lambda n: (n.value.f is f) if isinstance(n.value, CallInfo) else (n.parent().value.f is f)
		return self.filter(filter_predicate)
	def for_object(self, obj):
		filter_predicate = lambda n: (n.value.obj is obj) if isinstance(n.value, CallInfo) else (n.parent().value.obj is obj)
		tr = self.filter(filter_predicate)
		for n in tr.descendants():
			if isinstance(n.value, CallInfo):
				n.value = CallInfo(None, n.value.f, n.value.vargs, n.value.kwargs, n.value.returned, n.value.raised)
		return tr
	
	def add_child(self, value=None):
		child = self.__class__(value=value, parent=self)
		self.add_child_node(child)
		return child
	def add_child_node(self, child):
		self.child_list.append(child)
	def remove_child_node(self, child):
		if child not in self.children(): raise ValueError('child not found')
		self.child_list.remove(child)
	
	def __len__(self):
		return len(self.child_list)
	def __getitem__(self, index):
		return self.child_list[index]
	def __contains__(self, x):
		return any( x == node.value for node in self.descendants() )
	def __str__(self):
		def format_node(node):
			first_line = '*' if node.value is None else repr(node.value)
			children = node.children()
			n = len(children)
			if n == 0:
				return [ first_line ]
			space = ' '*len(first_line)
			rows = []
			for i in range(0, n):
				child_rows = format_node(children[i])
				if i == 0:
					rows.append(first_line + ' +-> ' + child_rows[0])
				else:
					rows.append(space + ' +-> ' + child_rows[0])
				prefix = ' |   ' if i < n-1 else '     '
				rows.extend(space + prefix + cr for cr in child_rows[1:])
				if i < n-1:
					rows.append(space + ' |')
			return rows
		return '\n'.join(format_node(self))
	def __repr__(self):
		params = []
		children = self.children()
		if len(children) > 0:
			params.append(repr(children))
		if self.value is not None:
			params.append('value='+repr(self.value))
		return '{0}({1})'.format(self.__class__.__name__, ', '.join(params))

# record info about a function call
class CallInfo:
	def __init__(self, obj, f, vargs, kwargs, returned=None, raised=None):
		self.obj = obj
		self.f = f
		self.vargs = deepcopy(vargs)
		self.kwargs = deepcopy(kwargs)
		self.returned = deepcopy(returned)
		self.raised = raised
	def argstring(self):
		return ', '.join([repr(v) for v in self.vargs] + ['{0}={1}'.format(k,repr(v)) for (k,v) in self.kwargs.items()])
	def __repr__(self):
		return '{0}{1}({2})'.format(CallInfo.object_id(self.obj), self.f.__name__, self.argstring())
	@staticmethod
	def object_id(obj):
		return '' if obj is None else '{0}@0x{1:08X}.'.format(obj.__class__.__name__, id(obj))

# object for logging function calls in a call tree
class Tracer:
	def __init__(self):
		self.call_tree = CallTree()
		self.current_node = self.call_tree
		self.is_suspended = 0
	def clear_call_tree(self):
		self.call_tree.child_list = []
		self.current_node = self.call_tree
	def print_call_tree(self):
		print(self.call_tree)
	def push(self, ci):
		if not self.is_suspended:
			self.current_node = self.current_node.add_child(ci)
	def pop(self, returned=None, raised=None):
		if not self.is_suspended:
			if returned is not None:
				returned = deepcopy(returned)
				self.current_node.value.returned = returned
				self.current_node.add_child(returned)
			elif raised is not None:
				self.current_node.value.raised = raised
				self.current_node.add_child('raised {0}'.format(repr(raised)))
			self.current_node = self.current_node.parent()
	def suspend(self):
		self.is_suspended += 1
	def unsuspend(self):
		self.is_suspended -= 1
	def log_call(self, obj, f, vargs, kwargs):
		if not self.is_suspended:
			ci = CallInfo(obj, f, vargs, kwargs)
			self.push(ci)
		try:
			if obj is None:
				output = f(*vargs, **kwargs)
			else:
				output = f(obj, *vargs, **kwargs)
			self.pop(returned=output)
			return output
		except:
			e = sys.exc_info()[0]
			self.pop(raised=e)
			raise

__global_tracer__ = Tracer()
def print_call_tree(t=None):
	if t is None:
		__global_tracer__.print_call_tree()
	elif hasattr(t, 'print_call_tree'):
		t.print_call_tree()
	else:
		raise ValueError()
def clear_call_tree(t=None):
	if t is None:
		__global_tracer__.clear_call_tree()
	elif hasattr(t, 'clear_call_tree'):
		t.clear_call_tree()
	else:
		raise ValueError()

# decorator to trace function calls
def trace_calls(f):
	return use_tracer(__global_tracer__)(f)

# decorator to trace function calls to a given tracer object
def use_tracer(tracer_obj):
	tracer_obj = __get_tracer_of__(tracer_obj)
	def decorator(f):
		@wraps(f)
		def func_wrapper(*vargs, **kwargs):
			return tracer_obj.log_call(None, f, vargs, kwargs)
		func_wrapper.__tracer__ = tracer_obj
		func_wrapper.print_call_tree = lambda: print(tracer_obj.call_tree.for_function(f))
		func_wrapper.clear_call_tree = tracer_obj.clear_call_tree
		return func_wrapper
	return decorator

# returns a dynamically-created subclass (or proxy object) which logs method calls
def tracer(cls, methods=None, tracer_obj=None):
	if not isinstance(cls, type) and hasattr(cls, '__class__'):
		# if input is an object, return an object
		return tracer(cls.__class__)(cls)
	proxy_cls = type(cls.__name__, (cls,TracerProxy), dict())
	# don't wrap these attributes
	d = set(dir(cls)) - {
		'__new__', '__init__', '__setattr__', '__getattribute__', '__delattr__',
		'__class__', '__dir__', '__dict__', '__sizeof__', '__repr__', '__iter__',
		'__reduce__', '__reduce_ex__', '__getstate__', '__setstate__', '__deepcopy__',
	}
	if methods is not None:
		d &= set(methods)
	for a in d:
		v = getattr(cls, a)
		t = type(cls.__dict__[a] if a in cls.__dict__ else v).__name__
		if t in ['function', 'method', 'method_descriptor', 'wrapper_descriptor']:
			v = trace_method_calls(v)
		setattr(proxy_cls, a, v)
	def proxy_init(obj, *vargs, **kwargs):
		obj.__tracer__ = __global_tracer__ if tracer_obj is None else tracer_obj
		obj.__trace_suspended__ = 0
		if hasattr(cls, '__init__'):
			obj.__tracer__.log_call(obj, cls.__init__, vargs, kwargs)
	proxy_cls.__init__ = proxy_init
	proxy_cls.__traced_class__ = cls
	proxy_cls.__tracer__ = tracer_obj
	return proxy_cls

class TracerProxy:
	def print_call_tree(self):
		print(self.__tracer__.call_tree.for_object(self))
	def clear_call_tree(self):
		self.__tracer__.clear_call_tree()
	def __reduce_ex__(self, n):
		# super().__reduce_ex__ calls __iter__, which is traced by log_call; log_call calls deepcopy, which calls __reduce_ex__.
		# therefore, to avoid infinite recursion we must suspend tracing while we evaluate super().__reduce_ex__
		self.__tracer__.suspend()
		o = super().__reduce_ex__(n)
		self.__tracer__.unsuspend()
		return o

# decorator to trace method calls
def trace_method_calls(f):
	@wraps(f)
	def func_wrapper(obj, *vargs, **kwargs):
		return obj.__tracer__.log_call(obj, f, vargs, kwargs)
	return func_wrapper

def __get_tracer_of__(obj):
	if isinstance(obj, Tracer):
		return obj
	elif hasattr(obj, '__tracer__'):
		return obj.__tracer__
	else:
		raise TypeError('obj must be a Tracer object or another traced function or object')
