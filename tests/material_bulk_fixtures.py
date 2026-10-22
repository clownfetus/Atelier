"""Synthetic material graphs shared by the isolated batch and browser checks."""
BASE = "Fixture/Materials/M_Base"
NEW_PARENT = "Fixture/Materials/M_Alternate"
INSTANCE_PARENT = "Fixture/Materials/MI_Parent"
SOURCE = "Fixture/Materials/MI_Source"


def material(gr, opacity=.75, parent=BASE, parent_class="Material", kind="MaterialInstanceConstant"):
    def parameter(name, value):
        return {"OriginalStructHeader": {"keep": True}, "Value": [
            {"Name": "ParameterInfo", "Value": [{"Name": "Name", "Value": name}]},
            {"Name": "ParameterValue", "Value": value, "IsZero": value == 0}]}
    scalars = [parameter("Speed", 1.234567891)]
    if opacity is not None:
        scalars.append(parameter("Opacity", opacity))
    return {"FolderName": "/Game/Marvel/" + gr, "NameMap": [gr.rsplit("/", 1)[-1]],
            "Imports": [{"ObjectName": kind, "OuterIndex": 0},
                        {"ObjectName": "/Game/Marvel/" + parent, "OuterIndex": 0},
                        {"ObjectName": parent.rsplit("/", 1)[-1], "ClassName": parent_class, "OuterIndex": -2},
                        {"ObjectName": "/Game/Marvel/Fixture/T_Base", "OuterIndex": 0},
                        {"ObjectName": "T_Base", "ClassName": "Texture2D", "OuterIndex": -4}],
            "Exports": [{"ObjectName": gr.rsplit("/", 1)[-1], "OuterIndex": 0, "ClassIndex": -1,
                         "Extras": "preserved cooked shader", "Data": [
                             {"Name": "Parent", "Value": -3},
                             {"Name": "StaticParametersRuntime", "Value": [{"switch": True}]},
                             {"Name": "VectorParameterValues", "Value": [parameter("Tint", [{"Value": {
                                 "R": .25, "G": .123456789, "B": 2.5, "A": .375}}])]},
                             {"Name": "ScalarParameterValues", "Value": scalars},
                             {"Name": "TextureParameterValues", "Value": [parameter("BaseColor", -5)]}]}]}
