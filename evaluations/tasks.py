"""Small, deterministic maintenance tasks; these are not model-quality results."""

STARTERS = {
    "intervals": "def merge_intervals(intervals):\n    return sorted(intervals)\n",
    "topo": "def topological_order(dependencies):\n    return sorted(dependencies)\n",
    "ndjson": "import json\ndef parse_chunks(chunks):\n    return [json.loads(line) for chunk in chunks for line in chunk.decode('utf-8').splitlines() if line.strip()]\n",
    "lru": """class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.data = {}
    def get(self, key, default=None):
        return self.data.get(key, default)
    def put(self, key, value):
        self.data[key] = value
        if len(self.data) > self.capacity:
            self.data.pop(next(reversed(self.data)))
    def keys(self):
        return list(self.data)
""",
}

# Only used to check the grader. The live agent receives STARTERS and its prompt.
ORACLES = {
    "intervals": """def merge_intervals(intervals):
    values = sorted(tuple(pair) for pair in intervals)
    result = []
    for start, end in values:
        if start > end:
            raise ValueError('reversed interval')
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result
""",
    "topo": """import heapq
def topological_order(dependencies):
    deps = {name: set(values) for name, values in dependencies.items()}
    nodes = set(deps)
    for values in deps.values():
        nodes.update(values)
    outgoing = {name: set() for name in nodes}
    degree = {name: len(deps.get(name, set())) for name in nodes}
    for name, values in deps.items():
        for dependency in values:
            outgoing[dependency].add(name)
    ready = [name for name in nodes if degree[name] == 0]
    heapq.heapify(ready)
    result = []
    while ready:
        name = heapq.heappop(ready)
        result.append(name)
        for successor in outgoing[name]:
            degree[successor] -= 1
            if degree[successor] == 0:
                heapq.heappush(ready, successor)
    if len(result) != len(nodes):
        raise ValueError('cycle')
    return result
""",
    "ndjson": """import json
def parse_chunks(chunks):
    text = b''.join(chunks).decode('utf-8')
    return [json.loads(line) for line in text.split('\\n') if line.strip()]
""",
    "lru": """from collections import OrderedDict
class LRUCache:
    def __init__(self, capacity):
        if capacity < 0:
            raise ValueError('negative capacity')
        self.capacity = capacity
        self.data = OrderedDict()
    def get(self, key, default=None):
        if key not in self.data:
            return default
        self.data.move_to_end(key)
        return self.data[key]
    def put(self, key, value):
        self.data[key] = value
        self.data.move_to_end(key)
        while len(self.data) > self.capacity:
            self.data.popitem(last=False)
    def keys(self):
        return list(self.data)
""",
}
