
# TEAM 40 - STRUCTURAL MODEL COMPARISON
# Quantity comparison for Teams 41 and 42.

from pathlib import Path
from collections import defaultdict
import math
import re

import pandas as pd
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as el
import ifcopenshell.util.unit as unit
import ifcopenshell.util.shape as shape


# ==================================================
# 1. SETTINGS
# ==================================================

HOME = Path(__file__).resolve().parent

MODELS = [
    "B308X.ifc",
    "26-06-D-STR.ifc",
    "26-09-D-STR.ifc",
]

CLASSES = [
    "IfcBeam",
    "IfcColumn",
    "IfcWall",
    "IfcSlab",
]

LENGTH_TOLERANCE = 0.01
QUANTITY_TOLERANCE = 0.01

MEASURES = [
    "Length_m",
    "Area_m2",
    "Volume_m3",
]

ELEMENT_COLUMNS = [
    "GlobalId",
    "IfcClass",
    "Material",
    "TypeName",
    "Name",
    "Storey",
    *MEASURES,
    "LengthSource",
    "AreaSource",
    "VolumeSource",
]

GROUP_KEYS = [
    "Status",
    "IfcClass",
    "Material",
    "TypeName",
    "IndividualLength_m",
]

GROUP_COLUMNS = [
    "GlobalId",
    "Status",
    "IfcClass",
    "Material",
    "TypeName",
    "Count",
    "Length_m",
    "Area_m2",
    "Volume_m3",
    "ElementsWithoutVolume",
    "IndividualLength_m",
]

MATCH_COLUMNS = [
    "ExistingGlobalId",
    "ProposedGlobalId",
    "ExistingName",
    "ProposedName",
    "IfcClass",
    "Material",
    "TypeName",
    "ExistingLength_m",
    "ProposedLength_m",
    "ExistingArea_m2",
    "ProposedArea_m2",
    "ExistingVolume_m3",
    "ProposedVolume_m3",
    "VolumeDifference_m3",
    "MatchMethod",
    "Result",
]


# ==================================================
# 2. CAPT - READ IFC DATA
# ==================================================

def valid_number(value):

    try:

        return (
            value is not None
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > 0
        )

    except (ValueError, TypeError):

        return False


def normalized(value):

    if pd.isna(value):
        return ""

    return re.sub(
        r"\s+",
        "",
        str(value).lower(),
    )


def records(df):

    return df.astype(object).where(
        pd.notna(df),
        None,
    ).to_dict("records")


def wall_scope(item):

    typ = el.get_type(item)

    name = " ".join([
        item.Name or "",
        getattr(typ, "Name", "") or "",
    ]).lower()

    if re.search(
        r"\bin_|\binterior\b|\binternal\b|\binderv",
        name,
    ):

        return "interior"

    if re.search(
        r"\bba_|\bfo_|foundation|basement",
        name,
    ):

        return "review"

    if re.search(
        r"\bex_|\bexterior\b|\bexternal\b|\byderv",
        name,
    ):

        return "exterior"

    flag = el.get_pset(
        item,
        "Pset_WallCommon",
        "IsExternal",
    )

    if flag is True:
        return "exterior"

    if flag is False:
        return "interior"

    return "review"


def CAPT_MATERIAL(item):

    materials = el.get_materials(item)

    names = sorted(set(
        material.Name
        for material in materials
        if material.Name
    ))

    return " | ".join(names) if names else "NO MATERIAL"


def CONVERT_QUANTITY(
    model,
    value,
    explicit_unit,
    dimension,
):

    if explicit_unit:

        target_name = {
            "LENGTH": "METRE",
            "AREA": "SQUARE_METRE",
            "VOLUME": "CUBIC_METRE",
        }[dimension]

        target = model.create_entity(
            "IfcSIUnit",
            UnitType=dimension + "UNIT",
            Name=target_name,
        )

        try:

            return unit.convert_unit(
                value,
                explicit_unit,
                target,
            )

        finally:

            model.remove(target)

    scale = unit.calculate_unit_scale(
        model,
        dimension + "UNIT",
    )

    return value * scale


def CAPT_QUANTITY(
    model,
    item,
    names,
    dimension,
):

    sources = [
        item,
        el.get_type(item),
    ]

    # Read IFC Quantity Sets.

    for name in names:

        for source in sources:

            if source is None:
                continue

            quantity_sets = el.get_psets(
                source,
                qtos_only=True,
                should_inherit=False,
            )

            for data in quantity_sets.values():

                qset = model.by_id(data["id"])

                for q in getattr(
                    qset,
                    "Quantities",
                    (),
                ):

                    if q.Name != name:
                        continue

                    if not q.is_a(
                        "IfcQuantity" + dimension.title()
                    ):

                        continue

                    value = getattr(
                        q,
                        dimension.title() + "Value",
                        None,
                    )

                    if not valid_number(value):
                        continue

                    try:

                        result = CONVERT_QUANTITY(
                            model,
                            value,
                            q.Unit,
                            dimension,
                        )

                        if valid_number(result):

                            return result, "Qto"

                    except Exception:

                        continue

    # Read ordinary Property Sets.

    expected_measure = {
        "LENGTH": "IfcLengthMeasure",
        "AREA": "IfcAreaMeasure",
        "VOLUME": "IfcVolumeMeasure",
    }[dimension]

    for name in names:

        for source in sources:

            if source is None:
                continue

            properties = el.get_psets(
                source,
                psets_only=True,
                should_inherit=False,
            )

            for data in properties.values():

                pset = model.by_id(data["id"])

                for prop in getattr(
                    pset,
                    "HasProperties",
                    (),
                ):

                    if prop.Name != name:
                        continue

                    if not prop.is_a(
                        "IfcPropertySingleValue"
                    ):

                        continue

                    nominal = prop.NominalValue

                    if nominal is None:
                        continue

                    if not nominal.is_a(
                        expected_measure
                    ):

                        continue

                    value = nominal.wrappedValue

                    if not valid_number(value):
                        continue

                    try:

                        result = CONVERT_QUANTITY(
                            model,
                            value,
                            prop.Unit,
                            dimension,
                        )

                        if valid_number(result):

                            return result, "Pset"

                    except Exception:

                        continue

    return None, None


def CAPT_SECTION(
    item,
    cls,
    thickness,
    scale,
):

    typ = el.get_type(item)

    name = (
        getattr(typ, "Name", None)
        or item.Name
        or ""
    )

    # Walls and slabs.

    if cls in ("IfcWall", "IfcSlab"):

        if thickness is None:

            material = el.get_material(
                item,
                should_skip_usage=True,
            )

            if material and material.is_a(
                "IfcMaterialLayerSet"
            ):
                thickness = sum(
                    layer.LayerThickness
                    for layer in material.MaterialLayers
                ) * scale

        if valid_number(thickness):
            return f"t={thickness * 1000:.6g} mm"

        names = [
            name,
            item.Name or "",
        ]

        for text in names:

            match = re.search(
                r"(\d+(?:[.,]\d+)?)\s*mm\b",
                text,
                re.I,
            )

            if match:
                value = float(match[1].replace(",", "."))
                return f"t={value:.6g} mm"

            match = re.search(
                r"(?:wall|slab)[_\s-]+(\d+(?:[.,]\d+)?)(?=[:_\s-]|$)",
                text,
                re.I,
            )

            if match:
                value = float(match[1].replace(",", "."))

                if 50 <= value <= 2000:
                    return f"t={value:.6g} mm"

    # Beams and columns.

    else:
        for text in (name, item.Name or ""):

            match = re.search(
                r"\bIB\s*(\d+)\s*/\s*(\d+)\b",
                text,
                re.I,
            )

            if match:
                return f"IB{match[1]}/{match[2]}"
        material = el.get_material(
            item,
            should_skip_usage=True,
        )

        profiles = []

        if material and material.is_a(
            "IfcMaterialProfileSet"
        ):

            profiles.extend(
                p.Profile
                for p in material.MaterialProfiles
                if p.Profile
            )

        try:

            profiles.extend(
                shape.get_profiles(item)
            )

        except Exception:

            pass

        for profile in profiles:

            if profile.is_a(
                "IfcRectangleProfileDef"
            ):

                width = profile.XDim * scale * 1000
                height = profile.YDim * scale * 1000

                return f"{width:.6g}x{height:.6g}"

            if profile.is_a(
                "IfcCircleProfileDef"
            ):

                diameter = (
                    profile.Radius * 2 * scale * 1000
                )

                return f"D={diameter:.6g} mm"

            if profile.ProfileName:

                return profile.ProfileName

        match = re.search(
            r"\b(HEA|HEB|HEM|IPE|IPN|UPN)\s*(\d+)\b",
            name,
            re.I,
        )

        if match:

            return match[1].upper() + match[2]

        match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)",
            name,
            re.I,
        )

        if match:

            width = float(
                match[1].replace(",", ".")
            )

            height = float(
                match[2].replace(",", ".")
            )

            return f"{width:.6g}x{height:.6g}"

    return None


def CAPT_ELEMENTS(model):

    rows = []
    review = []

    settings = ifcopenshell.geom.settings()

    settings.set("use-world-coords", False)
    settings.set("convert-back-units", False)

    scale = unit.calculate_unit_scale(model)

    for cls in CLASSES:

        print("Reading:", cls)

        for item in model.by_type(cls):

            # Include exterior walls only.

            if cls == "IfcWall":

                scope = wall_scope(item)

                if scope == "review":

                    review.append(
                        f"{item.GlobalId}: {item.Name}"
                    )

                if scope != "exterior":

                    continue

            # Length.

            length = None
            length_source = None

            if cls in (
                "IfcBeam",
                "IfcColumn",
                "IfcWall",
            ):

                length, length_source = CAPT_QUANTITY(
                    model,
                    item,
                    (
                        "NetLength",
                        "Length",
                        "GrossLength",
                    ),
                    "LENGTH",
                )

            # Area.

            if cls == "IfcWall":

                area_names = (
                    "NetSideArea",
                    "GrossSideArea",
                )

            elif cls == "IfcSlab":

                area_names = (
                    "NetArea",
                    "GrossArea",
                )

            else:

                area_names = ()

            area, area_source = CAPT_QUANTITY(
                model,
                item,
                area_names,
                "AREA",
            )

            # Thickness.

            thickness = None

            if cls in ("IfcWall", "IfcSlab"):

                thickness, _ = CAPT_QUANTITY(
                    model,
                    item,
                    ("Thickness", "Width"),
                    "LENGTH",
                )

            # Net volume.

            volume, volume_source = CAPT_QUANTITY(
                model,
                item,
                ("NetVolume",),
                "VOLUME",
            )

            section = CAPT_SECTION(
                item,
                cls,
                thickness,
                scale,
            )

            # Geometry fallback.

            needs_length = (
                cls in (
                    "IfcBeam",
                    "IfcColumn",
                    "IfcWall",
                )
                and length is None
            )

            needs_area = (
                cls in ("IfcWall", "IfcSlab")
                and area is None
            )

            if (
                volume is None
                or needs_length
                or needs_area
            ):

                try:

                    created = (
                        ifcopenshell.geom.create_shape(
                            settings,
                            item,
                        )
                    )

                    geometry = created.geometry

                    if volume is None:

                        estimated_volume = (
                            shape.get_volume(geometry)
                        )

                        if valid_number(
                            estimated_volume
                        ):

                            volume = estimated_volume
                            volume_source = "Geometry"

                    if needs_length:

                        estimated_length = None

                        if cls in (
                            "IfcBeam",
                            "IfcWall",
                        ):

                            estimated_length = (
                                shape.get_x(geometry)
                            )

                        elif cls == "IfcColumn":

                            estimated_length = (
                                shape.get_z(geometry)
                            )

                        if valid_number(
                            estimated_length
                        ):

                            length = estimated_length

                            length_source = (
                                "Geometry estimate"
                            )

                    if needs_area:

                        estimated_area = None

                        if cls == "IfcWall":

                            estimated_area = (
                                shape.get_side_area(
                                    geometry,
                                    axis="Y",
                                )
                            )

                        elif cls == "IfcSlab":

                            estimated_area = (
                                shape.get_footprint_area(
                                    geometry
                                )
                            )

                        if valid_number(
                            estimated_area
                        ):

                            area = estimated_area

                            area_source = (
                                "Geometry estimate"
                            )

                except Exception as error:

                    print(
                        "Geometry warning:",
                        item.GlobalId,
                        error,
                    )

            storey = el.get_container(item)

            rows.append({

                "GlobalId": item.GlobalId,

                "IfcClass": cls,

                "Material": CAPT_MATERIAL(item),

                "TypeName": section,

                "Name": item.Name,

                "Storey": getattr(
                    storey,
                    "Name",
                    None,
                ),

                "Length_m": length,

                "Area_m2": area,

                "Volume_m3": volume,

                "LengthSource": length_source,

                "AreaSource": area_source,

                "VolumeSource": volume_source,

            })

    return pd.DataFrame(
        rows,
        columns=ELEMENT_COLUMNS,
    ), review


# ==================================================
# 3. COMP - COMPARE MODEL QUANTITIES
# ==================================================

def required_quantities(cls):

    required = ["Volume_m3"]

    if cls in (
        "IfcBeam",
        "IfcColumn",
        "IfcWall",
    ):

        required.append("Length_m")

    if cls in (
        "IfcWall",
        "IfcSlab",
    ):

        required.append("Area_m2")

    return required


def complete_data(row):

    material = normalized(row["Material"])
    section = normalized(row["TypeName"])

    if material in ("", "nomaterial"):

        return False

    if not section:

        return False

    for key in required_quantities(
        row["IfcClass"]
    ):

        if not valid_number(row[key]):

            return False

    return True


def material_section_key(row):

    return (

        row["IfcClass"],

        normalized(row["Material"]),

        normalized(row["TypeName"]),

    )


def same_quantities(a, b):

    if not complete_data(a):
        return False

    if not complete_data(b):
        return False

    if material_section_key(a) != (
        material_section_key(b)
    ):

        return False

    for key in required_quantities(
        a["IfcClass"]
    ):

        x = float(a[key])
        y = float(b[key])

        if key == "Length_m":

            if abs(x - y) > LENGTH_TOLERANCE:

                return False

        else:

            if not math.isclose(

                x,

                y,

                rel_tol=QUANTITY_TOLERANCE,

                abs_tol=0.000001,

            ):

                return False

    return True


def difference_score(a, b):

    score = 0.0

    for key in required_quantities(
        a["IfcClass"]
    ):

        x = float(a[key])
        y = float(b[key])

        score += (
            abs(x - y)
            / max(abs(x), abs(y), 0.000001)
        )

    return score


def COMP_VERSIONS(existing, proposed):

    old = existing.to_dict("records")
    new = proposed.to_dict("records")

    old_groups = defaultdict(list)
    new_groups = defaultdict(list)

    for i, row in enumerate(old):

        if complete_data(row):

            old_groups[
                material_section_key(row)
            ].append(i)

    for j, row in enumerate(new):

        if complete_data(row):

            new_groups[
                material_section_key(row)
            ].append(j)

    # Find equivalent elements using quantities.
    # Coordinates are not required.
    # GlobalIds are retained for traceability.

    candidates = {}

    for key, old_indices in old_groups.items():

        new_indices = new_groups.get(
            key,
            [],
        )

        for i in old_indices:

            possible = []

            for j in new_indices:

                if same_quantities(
                    old[i],
                    new[j],
                ):

                    possible.append(j)

            possible.sort(

                key=lambda j: (

                    difference_score(
                        old[i],
                        new[j],
                    ),

                    j,

                )

            )

            if possible:

                candidates[i] = possible

    # Maximum one-to-one matching.
    # Every element is matched at most once.

    matched_new = {}

    def find_match(i, visited):

        for j in candidates.get(i, []):

            if j in visited:

                continue

            visited.add(j)

            previous = matched_new.get(j)

            if previous is None or find_match(
                previous,
                visited,
            ):

                matched_new[j] = i

                return True

        return False

    for i in sorted(

        candidates,

        key=lambda i: (
            len(candidates[i]),
            i,
        ),

    ):

        find_match(i, set())

    matched_old = set(
        matched_new.values()
    )

    matched_proposed = set(
        matched_new.keys()
    )

    changes = []
    matches = []

    # Equivalent quantities.

    for j, i in sorted(
        matched_new.items()
    ):

        a = old[i]
        b = new[j]

        matches.append({

            "ExistingGlobalId": a["GlobalId"],

            "ProposedGlobalId": b["GlobalId"],

            "ExistingName": a["Name"],

            "ProposedName": b["Name"],

            "IfcClass": a["IfcClass"],

            "Material": a["Material"],

            "TypeName": a["TypeName"],

            "ExistingLength_m": a["Length_m"],

            "ProposedLength_m": b["Length_m"],

            "ExistingArea_m2": a["Area_m2"],

            "ProposedArea_m2": b["Area_m2"],

            "ExistingVolume_m3": a["Volume_m3"],

            "ProposedVolume_m3": b["Volume_m3"],

            "VolumeDifference_m3": (
                b["Volume_m3"] - a["Volume_m3"]
            ),

            "MatchMethod": "Quantity equivalence",

            "Result": "Equivalent",

        })

    # Unmatched existing elements.

    for i, row in enumerate(old):

        if i in matched_old:

            continue

        status = (

            "removed"

            if complete_data(row)

            else "review_existing"

        )

        changes.append({

            **row,

            "Status": status,

            "Model": "Existing",

        })

    # Unmatched proposed elements.

    for j, row in enumerate(new):

        if j in matched_proposed:

            continue

        status = (

            "new"

            if complete_data(row)

            else "review_proposed"

        )

        changes.append({

            **row,

            "Status": status,

            "Model": "Proposed",

        })

    changes_df = pd.DataFrame(

        changes,

        columns=[
            *ELEMENT_COLUMNS,
            "Status",
            "Model",
        ],

    )

    matches_df = pd.DataFrame(

        matches,

        columns=MATCH_COLUMNS,

    )

    return changes_df, matches_df


# ==================================================
# 4. CALC - GROUP CHANGED ELEMENTS
# ==================================================

def CALC_GROUPS(changes):

    changes = changes.copy()

    changes["GroupId"] = None

    changes["IndividualLength_m"] = pd.to_numeric(

        changes["Length_m"],

        errors="coerce",

    ).where(

        changes["IfcClass"].isin([
            "IfcBeam",
            "IfcColumn",
        ])

    ).round(3)

    rows = []

    grouped = changes.groupby(

        GROUP_KEYS,

        dropna=False,

        sort=True,

    )

    for i, (key, group) in enumerate(
        grouped,
        1,
    ):

        group_id = f"G{i:03d}"

        changes.loc[
            group.index,
            "GroupId",
        ] = group_id

        row = dict(
            zip(GROUP_KEYS, key)
        )

        # GlobalId is the group ID in Groups.
        # GroupId links Elements to Groups.

        row.update({

            "GlobalId": group_id,

            "Count": len(group),

            "ElementsWithoutVolume": int(
                group.Volume_m3.isna().sum()
            ),

        })

        for col in MEASURES:

            row[col] = pd.to_numeric(

                group[col],

                errors="coerce",

            ).sum(

                min_count=len(group)

            )

        rows.append(row)

    groups = pd.DataFrame(

        rows,

        columns=GROUP_COLUMNS,

    )

    return groups, changes


# ==================================================
# 5. CALC - NET MATERIAL QUANTITIES
# ==================================================

def CALC_NET_QUANTITIES(existing, proposed):

    keys = [
        "IfcClass",
        "Material",
        "TypeName",
    ]

    def summarize(data):

        rows = []

        for key, group in data.groupby(

            keys,

            dropna=False,

        ):

            row = dict(
                zip(keys, key)
            )

            row["Count"] = len(group)

            for col in MEASURES:

                row[col] = pd.to_numeric(

                    group[col],

                    errors="coerce",

                ).sum(

                    min_count=len(group)

                )

            rows.append(row)

        return pd.DataFrame(

            rows,

            columns=[
                *keys,
                "Count",
                *MEASURES,
            ],

        )

    old = summarize(existing)
    new = summarize(proposed)

    net = old.merge(

        new,

        on=keys,

        how="outer",

        suffixes=(
            "_Existing",
            "_Proposed",
        ),

        indicator=True,

    )

    for col in ["Count", *MEASURES]:

        old_col = col + "_Existing"
        new_col = col + "_Proposed"

        net.loc[
            net["_merge"] == "right_only",
            old_col,
        ] = 0

        net.loc[
            net["_merge"] == "left_only",
            new_col,
        ] = 0

        net[col + "_Net"] = (

            net[new_col]
            - net[old_col]

        )

    return net.drop(
        columns="_merge"
    )


# ==================================================
# 6. CHEK - QUALITY CONTROL
# ==================================================

def analyse(

    model,

    existing,

    names=("existing", "proposed"),

):

    # Support IFC models, DataFrames and extracted data.

    if isinstance(existing, tuple):

        old, old_review = existing

    elif isinstance(existing, pd.DataFrame):

        old = existing
        old_review = []

    else:

        old, old_review = CAPT_ELEMENTS(existing)

    new, new_review = CAPT_ELEMENTS(model)

    changes, matches = COMP_VERSIONS(
        old,
        new,
    )

    changes["Model"] = changes["Model"].replace({

        "Existing": names[0],

        "Proposed": names[1],

    })

    # Only new and removed are allowed in Groups.

    review = changes[

        changes["Status"].str.startswith(
            "review",
            na=False,
        )

    ].copy()

    confirmed_format = changes[

        changes["Status"].isin([
            "new",
            "removed",
        ])

    ].copy()

    groups, grouped_elements = CALC_GROUPS(
        confirmed_format
    )

    # Incomplete elements are kept separately.

    net = CALC_NET_QUANTITIES(
        old,
        new,
    )

    all_elements = pd.concat(

        [old, new],

        ignore_index=True,

    )

    # Count matching GlobalIds for documentation.

    shared_ids = (

        set(old.GlobalId.dropna())

        & set(new.GlobalId.dropna())

    )

    shared_percentage = (

        len(shared_ids) / len(old)

        if len(old)

        else 0

    )

    new_count = int(

        (changes.Status == "new").sum()

    )

    removed_count = int(

        (changes.Status == "removed").sum()

    )

    review_existing = int(

        (
            changes.Status
            == "review_existing"
        ).sum()

    )

    review_proposed = int(

        (
            changes.Status
            == "review_proposed"
        ).sum()

    )

    equivalent_count = len(matches)

    missing_volumes = int(

        all_elements.Volume_m3.isna().sum()

    )

    length_required = all_elements.IfcClass.isin([

        "IfcBeam",
        "IfcColumn",
        "IfcWall",

    ])

    area_required = all_elements.IfcClass.isin([

        "IfcWall",
        "IfcSlab",

    ])

    missing_lengths = int(

        (
            length_required
            & all_elements.Length_m.isna()
        ).sum()

    )

    missing_areas = int(

        (
            area_required
            & all_elements.Area_m2.isna()
        ).sum()

    )

    estimated_lengths = int(

        (
            all_elements.LengthSource
            == "Geometry estimate"
        ).sum()

    )

    estimated_areas = int(

        (
            all_elements.AreaSource
            == "Geometry estimate"
        ).sum()

    )

    geometry_volumes = int(

        (
            all_elements.VolumeSource
            == "Geometry"
        ).sum()

    )

    warnings = []

    if shared_percentage < 0.30:

        warnings.append(

            "Low GlobalId overlap. Alternative quantity "
            "matching is used. Confirm this method "
            "with Teams 41 and 42."

        )

    if equivalent_count == 0:

        warnings.append(

            "No equivalent quantities identified "
            "within the selected tolerances."

        )

    if missing_volumes:

        warnings.append(
            "Some elements have missing volumes."
        )

    if missing_lengths:

        warnings.append(
            "Some elements have missing lengths."
        )

    if missing_areas:

        warnings.append(
            "Some elements have missing areas."
        )

    if (
        all_elements.Material == "NO MATERIAL"
    ).any():

        warnings.append(
            "Some materials are missing."
        )

    if all_elements.TypeName.isna().any():

        warnings.append(
            "Some structural sections are missing."
        )

    if all_elements.Material.fillna("").str.contains(

        " | ",

        regex=False,

    ).any():

        warnings.append(

            "Multi-material volumes are not split "
            "by individual material."

        )

    if estimated_lengths or estimated_areas:

        warnings.append(

            "Geometry-based length and area "
            "estimates require verification."

        )

    if old_review or new_review:

        warnings.append(

            "Unclassified, basement and foundation "
            "walls are excluded pending review."

        )

    if review_existing or review_proposed:

        warnings.append(

            "Incomplete elements are excluded from "
            "Groups and listed in Review. Groups "
            "therefore do not cover all elements."

        )

    # Verify element count balance.

    existing_balance = (

        equivalent_count
        + removed_count
        + review_existing
        == len(old)

    )

    proposed_balance = (

        equivalent_count
        + new_count
        + review_proposed
        == len(new)

    )

    if not existing_balance or not proposed_balance:

        raise RuntimeError(
            "Element count balance failed."
        )

    # Verify Groups format.

    if not groups.Status.isin([
        "new",
        "removed",
    ]).all():

        raise RuntimeError(
            "Invalid Groups status."
        )

    if groups.Count.sum() != len(grouped_elements):

        raise RuntimeError(
            "Group count balance failed."
        )

    # Info sheet.

    info = [

        ("Existing model", names[0]),

        ("Proposed model", names[1]),

        (
            "Result status",

            "Preliminary net quantity assessment",

        ),

        (
            "Comparison method",

            "Elements are compared based on material, "
            "cross-section, dimensions and quantities, "
            "independently of GlobalIds and spatial "
            "location.",

        ),

        (
            "Assumption",

            "Equivalent elements are assumed to be "
            "retained for the purpose of net "
            "quantity assessment.",

        ),

        (
            "Limitation",

            "Quantity equivalence does not establish "
            "physical retention. Demolition and "
            "replacement of equivalent elements "
            "cannot be identified by this method.",

        ),

        (
            "Scope",

            "Beams, columns, slabs and exterior walls.",

        ),

        ("Existing elements", len(old)),

        ("Proposed elements", len(new)),

        (
            "Shared GlobalIds",

            f"{shared_percentage:.1%}",

        ),

        (
            "Shared GlobalIds denominator",

            "Existing filtered elements",

        ),

        (
            "Equivalent elements",

            equivalent_count,

        ),

        (
            "Net added elements",

            new_count,

        ),

        (
            "Net removed elements",

            removed_count,

        ),

        (
            "Existing elements requiring review",

            review_existing,

        ),

        (
            "Proposed elements requiring review",

            review_proposed,

        ),

        (
            "Groups status",

            "new and removed represent unmatched "
            "quantities, not verified construction "
            "or demolition activities.",

        ),

        (
            "Length matching tolerance",

            "10 mm",

        ),

        (
            "Area and volume tolerance",

            "1% relative",

        ),

        (
            "Length grouping precision",

            "1 mm",

        ),

        (
            "Grouping",

            "Status, IFC class, material, section "
            "and individual beam or column length.",

        ),

        ("Missing volumes", missing_volumes),

        ("Missing lengths", missing_lengths),

        ("Missing areas", missing_areas),

        ("Estimated lengths", estimated_lengths),

        ("Estimated areas", estimated_areas),

        ("Geometry-based volumes", geometry_volumes),

        (
            "Matched volume difference (m3)",

            float(
                matches.VolumeDifference_m3.sum()
            ),

        ),

        (
            "Existing count balance",

            "OK" if existing_balance else "FAILED",

        ),

        (
            "Proposed count balance",

            "OK" if proposed_balance else "FAILED",

        ),

        (
            "NetQuantities",

            "Direct difference between existing and "
            "proposed quantities, including small "
            "differences within matched quantities.",

        ),

        (
            "Review",

            "Elements with incomplete comparison data. "
            "Excluded from Groups and requiring review.",

        ),

        (
            "Application",

            "Preliminary quantity data for cost "
            "and CO2 assessment. Confirm matching "
            "assumptions and review excluded elements "
            "before final calculations.",

        ),

        (
            "Quality notes",

            " | ".join(warnings)

            or "No additional issues detected.",

        ),

    ]

    info.extend(

        ("Existing wall to review", x)

        for x in old_review

    )

    info.extend(

        ("Proposed wall to review", x)

        for x in new_review

    )

    # Return lists of dictionaries for compatibility
    # with Teams 41 and 42 and runall.py.

    return {

        "groups": records(groups),

        "elements": records(grouped_elements),

        "matches": records(matches),

        "net": records(net),

        "review": records(review),

        "info": [

            {
                "Item": key,
                "Value": value,
            }

            for key, value in info

        ],

        "warnings": warnings,

    }


# ==================================================
# 7. COMM - EXPORT EXCEL
# ==================================================

def COMM_EXCEL(result, path):

    path = Path(path)

    path.parent.mkdir(

        parents=True,

        exist_ok=True,

    )

    with pd.ExcelWriter(

        path,

        engine="openpyxl",

    ) as writer:

        # Required sheet: Groups.

        pd.DataFrame(

            result["groups"],

            columns=GROUP_COLUMNS,

        ).to_excel(

            writer,

            sheet_name="Groups",

            index=False,

        )

        # Required sheet: Elements.

        pd.DataFrame(

            result["elements"],

            columns=[

                *ELEMENT_COLUMNS,

                "Status",

                "Model",

                "IndividualLength_m",

                "GroupId",

            ],

        ).to_excel(

            writer,

            sheet_name="Elements",

            index=False,

        )

        # Required sheet: Info.

        pd.DataFrame(

            result["info"],

            columns=[
                "Item",
                "Value",
            ],

        ).to_excel(

            writer,

            sheet_name="Info",

            index=False,

        )

        # Additional sheet: Matches.

        pd.DataFrame(

            result["matches"],

            columns=MATCH_COLUMNS,

        ).to_excel(

            writer,

            sheet_name="Matches",

            index=False,

        )

        # Additional sheet: NetQuantities.

        pd.DataFrame(

            result["net"],

        ).to_excel(

            writer,

            sheet_name="NetQuantities",

            index=False,

        )

        # Additional sheet: Review.

        pd.DataFrame(

            result["review"],

            columns=[

                *ELEMENT_COLUMNS,

                "Status",

                "Model",

            ],

        ).to_excel(

            writer,

            sheet_name="Review",

            index=False,

        )

        # Simple white Excel formatting.

        for ws in writer.sheets.values():

            ws.freeze_panes = "A2"

            ws.auto_filter.ref = ws.dimensions

            for col in ws.columns:

                width = max(

                    len(str(cell.value))

                    if cell.value is not None

                    else 0

                    for cell in col

                ) + 2

                ws.column_dimensions[
                    col[0].column_letter
                ].width = min(

                    60,

                    max(12, width),

                )

            for row in ws.iter_rows(
                min_row=2
            ):

                for cell in row:

                    if isinstance(
                        cell.value,
                        float,
                    ):

                        cell.number_format = (
                            "0.######"
                        )


# ==================================================
# 8. RUN BOTH COMPARISONS
# ==================================================

def main():

    print(
        "TEAM 40 - STRUCTURAL MODEL COMPARISON"
    )

    print(
        "-------------------------------------"
    )

    original_path = (

        HOME

        / "models"

        / MODELS[0]

    )

    print("Reading:", MODELS[0])

    existing = CAPT_ELEMENTS(

        ifcopenshell.open(
            str(original_path)
        )

    )

    for filename in MODELS[1:]:

        print(
            "-------------------------------------"
        )

        print(
            "Comparing:",
            filename,
        )

        model_path = (

            HOME

            / "models"

            / filename

        )

        model = ifcopenshell.open(
            str(model_path)
        )

        result = analyse(

            model,

            existing,

            (
                MODELS[0],
                filename,
            ),

        )

        output_path = (

            HOME

            / "output"

            / f"changes_{Path(filename).stem}.xlsx"

        )

        COMM_EXCEL(

            result,

            output_path,

        )

        print(
            "Equivalent elements:",
            len(result["matches"]),
        )

        print(
            "Elements requiring review:",
            len(result["review"]),
        )

        print(
            "Created:",
            output_path,
        )

        for warning in result["warnings"]:

            print(
                "NOTE:",
                warning,
            )

    print(
        "-------------------------------------"
    )

    print(
        "Both Excel files have been created."
    )


if __name__ == "__main__":
    main()
