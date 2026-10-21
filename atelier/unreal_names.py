"""Keep new JSON FNames serializable without moving existing name-map indices."""


def add_names(document, *values):
    """Append literal names and the bases UAssetAPI needs for numeric suffixes.

    Its JSON reader treats Name_7 as base Name plus instance number 8. Merely
    adding the rendered Name_7 leaves a dummy FName that cannot be serialized.
    Leading-zero suffixes such as Name_07 remain literal names.
    """
    names = document.setdefault('NameMap', [])
    for value in values:
        if value not in names:
            names.append(value)
        base, separator, number = value.rpartition('_')
        if (base and separator and number.isascii() and number.isdecimal()
                and len(number) <= 10 and (len(number) == 1 or number[0] != '0')
                and int(number) <= 2_147_483_647 and base not in names):
            names.append(base)
