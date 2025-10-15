import math
import numpy as np

# Euclidean distance
def distance(a, b) -> float:
    assert(len(a) == len(b))

    v = 0.
    for x in a:
        for y in b:
            v += math.pow(x - y, 2)

    return math.sqrt(v)