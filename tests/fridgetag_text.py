"""A minimal reader for Fridge-tag `.txt` reports, used to round-trip the generator's output."""


def outline(text):
    """Nested dicts from the one-space-indented outline; `a: 1, b: 2` lines give several keys."""
    root, stack = {}, [(-1, None)]
    stack[0] = (-1, root)
    for line in text.split("\r\n"):
        if not line:
            continue
        depth = len(line) - len(line.lstrip(" "))
        while stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1]
        body = line.strip()
        if body.endswith(":"):
            node = {}
            parent[body[:-1]] = node
            stack.append((depth, node))
            continue
        for pair in body.split(", "):
            key, _, value = pair.partition(": ")
            parent[key] = value
    return root
