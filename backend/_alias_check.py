import ast
import glob

BUILTIN_OK = {'None', 'True', 'False', 'print', 'len', 'range', 'int', 'str', 'float', 'bool',
              'list', 'dict', 'set', 'tuple', 'min', 'max', 'sum', 'abs', 'type', 'isinstance',
              'Exception', 'ValueError', 'TypeError', 'KeyError', 'NameError', 'ImportError',
              'open', 'enumerate', 'zip', 'sorted', 'reversed', 'map', 'filter', 'any', 'all',
              'object', 'super', 'getattr', 'setattr', 'hasattr', 'next', 'id', 'round', 'dir',
              'vars', 'property', 'staticmethod', 'classmethod', 'repr', 'format', 'hash',
              'input', 'repr'}

for py in sorted(glob.glob('app/**/*.py', recursive=True)):
    if '__pycache__' in py or py.endswith('__init__.py'):
        continue
    src = open(py, encoding='utf-8').read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue

    bound = set()          # 文件级: import 绑定 + 赋值/def/参数绑定
    loads = set()          # 所有 Load 名

    def collect(node, local_bind):
        if isinstance(node, ast.Import):
            for a in node.names:
                local_bind.add(a.asname or a.name.split('.')[0])
            return
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                local_bind.add(a.asname or a.name)
            return
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                loads.add(node.id)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                local_bind.add(node.id)
            return
        if isinstance(node, ast.FunctionDef):
            # 函数内新绑定的参数/局部, 递归收集它的 loads(独立作用域)
            inner = set()
            for a in node.args.args:
                inner.add(a.arg)
            for d in node.args.defaults:
                collect(d, inner)
            for stmt in node.body:
                collect(stmt, inner)
            loads.update(inner & {x for x in inner if False})  # 无
            return
        if isinstance(node, (ast.Lambda,)):
            return
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                collect(stmt, local_bind)
            return
        for child in ast.iter_child_nodes(node):
            collect(child, local_bind)

    # 顶层作用域收集(函数体单独递归, 把函数体看作独立局部作用域)
    top_bound = set()
    def walk_branch(node):
        # 通用遍历: 记录模块级绑定; 进函数体用独立 bound 集合收集 loads
        if isinstance(node, ast.Import):
            for a in node.names:
                top_bound.add(a.asname or a.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                top_bound.add(a.asname or a.name)
        elif isinstance(node, ast.FunctionDef):
            inb = set()
            for a in (node.args.posonlyargs + node.args.args + node.args.kwonlyargs):
                inb.add(a.arg)
            if node.args.vararg: inb.add(node.args.vararg.arg)
            if node.args.kwarg: inb.add(node.args.kwarg.arg)
            for stmt in node.body:
                _scan(stmt, inb)     # 函数体: 局部绑定分析
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    top_bound.add(t.id)
        elif isinstance(node, ast.ClassDef):
            for stmt in node.body:
                walk_branch(stmt)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            top_bound.add(node.target.id)
        else:
            for child in ast.iter_child_nodes(node):
                walk_branch(child)

    def _scan(node, local):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                loads.add(node.id)
            else:
                local.add(node.id)
            return
        if isinstance(node, ast.Import):
            for a in node.names:
                local.add(a.asname or a.name.split('.')[0])
            return
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                local.add(a.asname or a.name)
            return
        if isinstance(node, ast.FunctionDef):
            inb = set()
            for a in (node.args.posonlyargs + node.args.args + node.args.kwonlyargs):
                inb.add(a.arg)
            if node.args.vararg: inb.add(node.args.vararg.arg)
            if node.args.kwarg: inb.add(node.args.kwarg.arg)
            for stmt in node.body:
                _scan(stmt, inb)
            return
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    local.add(t.id)
            for v in node.value:
                pass
        if isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            if isinstance(getattr(node, 'target', None), ast.Name):
                local.add(node.target.id)
        if isinstance(node, ast.For):
            if isinstance(node.target, ast.Name):
                local.add(node.target.id)
        if isinstance(node, ast.withitem) is not None and False:
            pass
        for child in ast.iter_child_nodes(node):
            _scan(child, local)

    for node in tree.body:
        walk_branch(node)

    module_bound = top_bound
    real_missing = sorted(n for n in loads
                          if n not in module_bound and n not in BUILTIN_OK)
    if real_missing:
        print(f'{py.split("/")[-1]:<28} 真缺失: {real_missing}')