import ast
import typing
import operator
import itertools
import functools
import contextlib

from copy import copy


class ValueGetter:
    """
    A value getter is a function that returns a value
    that is independent from variables in any namespace
    """


class NamespacedGetter:
    """
    A namespaced getter is a function that returns a value
    dependent on the current namespace
    """

    def __init__(self, namespace):
        self.namespace = namespace


class CallGetter(NamespacedGetter):
    """
    This is a function call that evaluates over a variable
    in the group over a single namespace
    """

    CALLS_MEANING = {
        "int": int,
        "bool": bool,
        "float": float,
        "str": str,
    }

    def _get_namespace_args(self, args):
        namespace = None
        for arg in args:
            try:
                arg_ns = arg.namespace
                if namespace and arg_ns != namespace:
                    raise ValueError(
                        "Function call can access at most one namespace "
                        "({} != {})".format(namespace, arg_ns)
                    )
                namespace = arg_ns
            except AttributeError:
                pass
        if namespace is None:
            raise ValueError(
                "Function calls with no namespace are unsupported"
            )
        return namespace

    def __init__(self, parsed_ast):
        try:
            self.function_name = parsed_ast.func.id
            self.function = self.CALLS_MEANING[parsed_ast.func.id]
        except KeyError:
            raise ValueError(
                "Unsupported function {}".format(parsed_ast.func.id)
            )

        self.args = [getter_from_ast(arg) for arg in parsed_ast.args]
        self.namespace = self._get_namespace_args(self.args)

    def __call__(self, variable_group):
        return self.function(*(arg(variable_group) for arg in self.args))

    def __str__(self):
        args = ",".join(str(x) for x in self.args)
        return "{}({})".format(self.function_name, args)


class AttributeGetter(NamespacedGetter):
    def __init__(self, parsed_ast):
        self.namespace = parsed_ast.value.id
        self.variable = parsed_ast.attr

    def __call__(self, variable_group):
        # resources are free form, support variable names not being unifrom
        try:
            return variable_group[self.variable]
        except KeyError:
            return None

    def __str__(self):
        return "{}.{}".format(self.namespace, self.variable)


class ConstantGetter(ValueGetter):
    def __init__(self, parsed_ast):
        self.value = parsed_ast.value

    def __call__(self, *args):
        return self.value

    @classmethod
    def from_unary_op(cls, parsed_ast):
        if not isinstance(parsed_ast.op, ast.USub):
            raise ValueError("Unsupported operator {}".format(parsed_ast))
        parsed_ast.operand.value *= -1
        return cls(parsed_ast.operand)

    def __str__(self):
        return str(self.value)


class ListGetter(ConstantGetter):
    def __init__(self, parsed_ast):
        values_getters = [getter_from_ast(value) for value in parsed_ast.elts]
        if any(
            isinstance(value, NamespacedGetter) for value in values_getters
        ):
            raise ValueError("Unsupported collection of non-constant values")
        self.value = [value_getter() for value_getter in values_getters]

    def __str__(self):
        to_r = ", ".join(str(x) for x in self.value)
        return "[{}]".format(to_r)


def getter_from_ast(parsed_ast):
    """
    Rappresents a way to get a value
    """
    getters = {
        ast.Call: CallGetter,
        ast.Attribute: AttributeGetter,
        ast.Constant: ConstantGetter,
        ast.List: ListGetter,
        ast.Tuple: ListGetter,
        ast.UnaryOp: ConstantGetter.from_unary_op,
    }
    try:
        getter = getters[type(parsed_ast)]
    except KeyError:
        raise ValueError("Unsupported name/value {}".format(parsed_ast))
    return getter(parsed_ast)


class Constraint:
    """
    Rappresents a filter to be applied on a namespace
    """

    def __init__(self, left_getter, operator, right_getter):
        if isinstance(left_getter, NamespacedGetter) and isinstance(
            right_getter, NamespacedGetter
        ):
            raise ValueError(
                "Unsupported comparison of namespaces with operands {} and {}".format(
                    left_getter, right_getter
                )
            )
        self.left_getter = left_getter
        self.operator = operator
        self.right_getter = right_getter
        try:
            self.namespace = self.left_getter.namespace
        except AttributeError:
            self.namespace = self.right_getter.namespace

    @classmethod
    def parse_from_ast(cls, parsed_ast):
        assert len(parsed_ast.ops) == 1
        assert len(parsed_ast.comparators) == 1
        left_getter = getter_from_ast(parsed_ast.left)
        right_getter = getter_from_ast(parsed_ast.comparators[0])
        return cls(left_getter, parsed_ast.ops[0], right_getter)

    def _filtered(self, ns_variables):
        def act_contains(x, y):
            # contains(a, b) == b in a
            # so we need to swap them around
            return operator.contains(y, x)

        def act_not_contains(x, y):
            return not act_contains(x, y)

        ast_to_operator = {
            ast.Eq: operator.eq,
            ast.NotEq: operator.ne,
            ast.GtE: operator.ge,
            ast.Gt: operator.gt,
            ast.LtE: operator.le,
            ast.In: act_contains,
            ast.NotIn: act_not_contains,
        }
        try:
            operator_f = ast_to_operator[type(self.operator)]
        except KeyError:
            raise ValueError("Unsupported operator {}".format(self.operator))

        return (
            variable_group
            for variable_group in ns_variables
            if operator_f(
                self.left_getter(variable_group),
                self.right_getter(variable_group),
            )
        )

    def filtered(self, namespaces):
        if self.namespace not in namespaces:
            return namespaces
        namespaces[self.namespace] = self._filtered(namespaces[self.namespace])
        return namespaces


class ConstraintExplainer(Constraint):
    def pretty_print(self, namespaces, namespace, max_namespace_items):
        namespaces[namespace] = list(namespaces[namespace])
        for filtered in namespaces[namespace][:max_namespace_items]:
            print("   ", filtered)
        if len(namespaces[namespace]) > max_namespace_items:
            print("    [...]")

    def filtered(self, namespaces, max_namespace_items=5):
        namespace = self.left_getter.namespace
        print(
            "Expression:",
            self.left_getter,
            ast.dump(self.operator),
            self.right_getter,
        )
        print("Filtering:", namespace)
        print("  Pre filter: ")
        self.pretty_print(namespaces, namespace, max_namespace_items)

        namespaces = super().filtered(namespaces)

        print("  Post filter: ")
        self.pretty_print(namespaces, namespace, max_namespace_items)

        return namespaces


def dct_hash(dict_obj):
    return hash(frozenset(dict_obj.items()))


def chain_uniq(*iterators):
    iterators = tuple(x for x in iterators if x)
    to_return = itertools.chain(*iterators)
    already_returned = set()
    for item in to_return:
        h_item = dct_hash(item)
        if h_item not in already_returned:
            already_returned.add(h_item)
            yield item


class Namespace:
    DEFAULT_NAMESPACE = "com.canonical.plainbox"

    def __init__(self, implicit_namespace, namespace):
        self.implicit_namespace = implicit_namespace
        self.namespace = namespace

    def __contains__(self, key):
        with contextlib.suppress(KeyError):
            _ = self[key]
            return True
        return False

    def __getitem__(self, key):
        """
        Namespaces keys are themselves namespaced. The priority of resolution
        is:
        1. key is in the namespace
        2. implicit_namespace::key is in the namespace
        3. DEFAULT_NAMESPACE::key is in the namespace (for example: manifest)
        """
        try:
            return self.namespace[key]
        except KeyError:
            with contextlib.suppress(KeyError):
                return self.namespace[
                    "{}::{}".format(self.implicit_namespace, key)
                ]
            with contextlib.suppress(KeyError):
                return self.namespace[
                    "{}::{}".format(self.DEFAULT_NAMESPACE, key)
                ]
            raise

    def __setitem__(self, key, value):
        if key in self.namespace:
            self.namespace[key] = value
            return

        implicit_namespaced_name = "{}::{}".format(
            self.implicit_namespace, key
        )
        if implicit_namespaced_name in self:
            self.namespace[implicit_namespaced_name] = value
            return

        builtin_namespaced_name = "{}::{}".format(self.DEFAULT_NAMESPACE, key)
        if builtin_namespaced_name in self:
            self.namespace[builtin_namespaced_name] = value
            return

        self.namespace[key] = value

    def items(self):
        return self.namespace.items()

    def keys(self):
        return self.namespace.keys()

    def values(self):
        return self.namespace.values()

    def get(self, key, default=None):
        with contextlib.suppress(KeyError):
            return self[key]
        return default

    def namespace_union(self, other: "Self"):
        return Namespace(
            self.implicit_namespace,
            {
                namespace_name: chain_uniq(
                    self.get(namespace_name),
                    other.get(namespace_name),
                )
                for namespace_name in (self.keys() | other.keys())
            },
        )

    def duplicate_namespace(self, count: int):
        duplicated_namespace = {
            x: itertools.tee(y, count) for (x, y) in self.items()
        }
        namespaces = [
            Namespace(
                self.implicit_namespace,
                {
                    key: duplicated_namespace[key][i]
                    for key in duplicated_namespace
                },
            )
            for i in range(count)
        ]
        return namespaces


@functools.singledispatch
def _prepare_filter(ast_item: ast.AST, namespace, constraint_class):
    """
    This function edits the namespace in place replacing each value
    with an iterator that returns only the values that were in the original
    namespace that match the parsed expression.

    Warning: This edits the input namespace in place

    Ex.
    input_namespace = { 'a' : [{'v' : 1}, {'v' : 2}] }
    parsed_expr ~= 'a.v > 1'
    output_namespace = {'a' : (x for x in input_namespace['a'] if x['v'] > 1) }
    """
    raise NotImplementedError(
        "Unsupported ast item: {}".format(ast.dump(ast_item))
    )


@_prepare_filter.register(ast.BoolOp)
def _prepare_boolop(bool_op, namespace, constraint_class):
    if isinstance(bool_op.op, ast.And):
        return functools.reduce(
            lambda ns, constraint: _prepare_filter(
                constraint, ns, constraint_class
            ),
            bool_op.values,
            namespace,
        )
    elif isinstance(bool_op.op, ast.Or):
        duplicated_namespaces = namespace.duplicate_namespace(
            len(bool_op.values)
        )
        ns_constraint = zip(duplicated_namespaces, bool_op.values)
        filtered_namespaces = (
            _prepare_filter(constraint, namespace, constraint_class)
            for namespace, constraint in ns_constraint
        )
        return functools.reduce(Namespace.namespace_union, filtered_namespaces)
    raise ValueError("Unsupported boolean operator: {}".format(bool_op.op))


@_prepare_filter.register(ast.Expression)
def _prepare_expression(ast_item, namespace, constraint_class):
    return _prepare_filter(ast_item.body, namespace, constraint_class)


@_prepare_filter.register(ast.Compare)
def _prepare_compare(ast_item, namespace, constraint_class):
    return constraint_class.parse_from_ast(ast_item).filtered(namespace)


def prepare(
    expr: typing.Union[ast.AST, str],
    namespace: dict,
    implicit_namespace: str = "",
    explain=False,
):
    """
    This function returns a namespace with the same keys and values that are
    iterators that returns only the values that were in the original namespace
    that match the parsed expression.

    Ex.
    input_namespace = { 'a' : [{'v' : 1}, {'v' : 2}] }
    parsed_expr ~= 'a.v > 1'
    output_namespace = {'a' : (x for x in input_namespace['a'] if x['v'] > 1) }

    When explain is True, the evaluating the resource expression will explain
    what each constraint did to the namespace affected

    Ex.
    Expression: namespace.a In() [1, 2]
    Filtering: namespace
      Pre filter:
        {'a': '1'}
        {'a': '2'}
        {'a': '3'}
      Post filter:
        {'a': '1'}
        {'a': '2'}
    """
    if explain:
        CC = ConstraintExplainer
    else:
        CC = Constraint
    if isinstance(expr, str):
        expr = ast.parse(expr, mode="eval")
    return _prepare_filter(
        expr, Namespace(implicit_namespace, copy(namespace)), CC
    )


def evaluate_lazy(
    expr: typing.Union[ast.AST, str],
    namespace: dict,
    implicit_namespace: str = "",
    explain=False,
) -> bool:
    """
    This returns the truth value of a prepared namespace.
    Returns a namespace where each value is True if any resource matched the
    expression

    To get a True/False answer one can simply use:
        all(evaluate_lazy(...).values())
    """
    namespace = prepare(
        expr, namespace, implicit_namespace=implicit_namespace, explain=explain
    )

    def any_next(iterable):
        try:
            next(iterable)
            return True
        except StopIteration:
            return False

    return {x: any_next(iter(v)) for (x, v) in namespace.items()}


def evaluate(
    expr: typing.Union[ast.AST, str],
    namespace: dict,
    implicit_namespace: str = "",
    explain=False,
):
    namespace = prepare(
        expr, namespace, implicit_namespace=implicit_namespace, explain=explain
    )
    return {
        namespace_name: list(values_iterator)
        for (namespace_name, values_iterator) in namespace.items()
    }