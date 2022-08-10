import numpy as np
import math





touru = 1000
share = 1000
stop = np.arange(0.02, 0.5, 0.005).tolist()
down_range = np.arange(1, 0.5, -0.001)
for pw in down_range:
    item = pw
    kuisun_ratio = (touru - share * item) / touru
    if kuisun_ratio >= stop[0] + 0.01:
        kuisun = (touru - share * item)
        share = ((kuisun / stop[0]) - touru) / item + share
        touru = kuisun / stop[0]
        print(item, kuisun, share, touru, stop[0])
        stop = stop[1:]
    kuisun_ratio = (touru - share * item) / touru
    print('kuisun:', kuisun_ratio)