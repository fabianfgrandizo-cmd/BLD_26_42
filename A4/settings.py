# Local IFC files (never uploaded to GitHub). Keep the r before the quotes on Windows.
# Relative paths are resolved from the A4 folder.

# Put every IFC you want to compare in this folder (the existing building AND the proposed versions)
MODELS_FOLDER = r"models"

# The file whose name contains this text is the existing (original) building; all other .ifc
# files in the folder are proposed versions. Not case-sensitive.
EXISTING_MODEL_NAME = "B308X"

# Name used by the course template (node-comply-template): where the models come from
MODEL_PATH = MODELS_FOLDER

# Leave out elements marked LoadBearing = False (e.g. partitions in an architectural model)
LOAD_BEARING_ONLY = True

# Models from different Revit files share no GlobalIds: elements are then matched by position.
# Two elements closer than this in plan (after automatic alignment) are the same element.
POSITION_TOLERANCE_M = 0.3
