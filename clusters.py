"""Single source of truth: Clearfolks product name → Hugo blog cluster slug.

Different parts of the pipeline emit slightly different product names — Echo's
signal prompt says "Caregiver Organizer App", sofia_blog speaks the canonical
"Caregiver Command Center", pin drafts use whichever variant the model picked
that day. This module collects every observed alias in one dict so any caller
can resolve a product name to a cluster without each one keeping its own copy.

Adding a new product? Add every name variant it might appear under here.
"""

from __future__ import annotations

PRODUCT_TO_CLUSTER: dict[str, str] = {
    # caregiver
    "Caregiver Command Center":        "caregiver",
    "Caregiver Organizer App":         "caregiver",

    # medication
    "Medication Tracker":              "medication",
    "Medication Tracker App":          "medication",

    # iep
    "IEP Parent Binder":               "iep",
    "IEP Parent Binder App":           "iep",
    "IEP Meeting Prep Kit":            "iep",

    # etsy-seller
    "Etsy Seller Business System":     "etsy-seller",
    "Etsy Seller Organizer App":       "etsy-seller",
    "Etsy Profit Tracker":             "etsy-seller",

    # wedding
    "Wedding Planning App":            "wedding",

    # baby
    "Baby Tracker and Postpartum App": "baby",
    "Baby Tracker & Postpartum App":   "baby",
    "Baby Tracker":                    "baby",

    # homeschool
    "Homeschool Planner App":          "homeschool",

    # pet-care
    "Pet Care Organizer":              "pet-care",
    "Pet Care Organizer App":          "pet-care",

    # meal-planning
    "Meal Planner and Grocery":        "meal-planning",
    "Meal Planner and Grocery App":    "meal-planning",
    "Meal Planner & Grocery":          "meal-planning",
    "Meal Planner & Grocery App":      "meal-planning",
    "Meal Planner":                    "meal-planning",

    # moving
    "Moving Day Organizer":            "moving",
    "Moving Day Organizer App":        "moving",

    # travel
    "Travel Planner":                  "travel",
    "Travel Planner App":              "travel",
}

DEFAULT_CLUSTER = "generic"


def product_to_cluster(product_name: str | None) -> str | None:
    """Resolve any product-name variant to its Hugo cluster slug.

    Returns None when the input is empty or unresolvable. Callers that want
    a fallback should do ``product_to_cluster(name) or DEFAULT_CLUSTER``.

    Tries: exact match → match after stripping a trailing " App".
    """
    if not product_name:
        return None
    if product_name in PRODUCT_TO_CLUSTER:
        return PRODUCT_TO_CLUSTER[product_name]
    base = product_name.removesuffix(" App").strip()
    if base in PRODUCT_TO_CLUSTER:
        return PRODUCT_TO_CLUSTER[base]
    return None
