


def method1(fund):
    ratio = fund.gz_ratio_day()
    if ratio >= -0.01:
        op = 100
    elif ratio >= -0.03:
        op = 200
    elif ratio >= -0.06:
        op = 300
    elif ratio >= -0.1:
        op = 400
    else:
        op = 500
    return op



