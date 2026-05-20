"""Per-product dashboard mockup data.

Used by mockup.py (hero image phone mockup) and video.py (scene 2) so each
product's visual asset shows a plausible in-app dashboard for that product,
not a recycled Baby Tracker screen.

DASHBOARD schema:
    app_title    — short product label shown as the phone's app header
    subtitle     — small line under the title ("Today · 3 …")
    caption      — one-line caption over the video's dashboard scene
    stats        — list of exactly 4 (label, value) tuples
    nav_icons    — 5 emoji/chars for the bottom navigation
    accent_cycle — optional list of 4 color names ("teal"/"navy"/"orange");
                   defaults to [teal, navy, orange, teal]
"""
from dataclasses import dataclass, field


@dataclass
class Dashboard:
    app_title: str
    subtitle: str
    caption: str
    stats: list                    # 4 × (label, value)
    nav_icons: list = field(default_factory=lambda: ["📊", "📝", "📅", "🔖", "⭐"])
    accent_cycle: list = field(default_factory=lambda: ["teal", "navy", "orange", "teal"])


DASHBOARDS: dict[str, Dashboard] = {
    # --- P0001 Caregiver Command Center ---
    "caregiver": Dashboard(
        app_title="Caregiver",
        subtitle="Today · 3 meds · 2 appts",
        caption="Medications, appointments, contacts — in one place",
        stats=[("Meds today", "3"), ("Next appt", "Apr 30"), ("Contacts", "2"), ("Notes", "2")],
        nav_icons=["📊", "💊", "📅", "👥", "📝"],
    ),
    # --- P0002 Medication Tracker ---
    "cf-bqs4r8e9": Dashboard(
        app_title="Medications",
        subtitle="4 active · next refill 12d",
        caption="Doses, refills, symptoms — never missed",
        stats=[("Active meds", "4"), ("Next refill", "12d"), ("Symptoms", "2"), ("Doctors", "2")],
        nav_icons=["📊", "💊", "⏰", "🩺", "📋"],
    ),
    # --- P0003 IEP Parent Binder ---
    "cf-9x25jxsc": Dashboard(
        app_title="IEP Binder",
        subtitle="3 goals · next review Jun",
        caption="Goals, meetings, services — documented",
        stats=[("Goals", "3"), ("Meetings", "2"), ("Services", "2"), ("Contacts", "3")],
        nav_icons=["📊", "🎯", "📅", "👥", "📁"],
        accent_cycle=["teal", "navy", "orange", "teal"],
    ),
    # --- P0004 IEP Meeting Prep Kit ---
    "cf-qatxssg7": Dashboard(
        app_title="Meeting Prep",
        subtitle="5 questions · 2 action items",
        caption="Questions, rights, notes — ready",
        stats=[("Questions", "5"), ("Actions", "2"), ("Rights", "8"), ("Notes", "1")],
        nav_icons=["📊", "❓", "⚖️", "✅", "📝"],
        accent_cycle=["teal", "orange", "navy", "teal"],
    ),
    # --- P0005 Etsy Seller Business System ---
    "cf-63nja3ht": Dashboard(
        app_title="Shop",
        subtitle="This month · $340 revenue",
        caption="Sales, fees, expenses — crystal clear",
        stats=[("Sales", "3"), ("Revenue", "$340"), ("Expenses", "$45"), ("Listings", "3")],
        nav_icons=["📊", "💰", "📦", "🏷️", "🧾"],
        accent_cycle=["teal", "navy", "orange", "teal"],
    ),
    # --- P0006 Wedding Planning App ---
    "cf-2465sd9i": Dashboard(
        app_title="Our Wedding",
        subtitle="Oct 23 · 184 days to go",
        caption="Budget, vendors, guests — coordinated",
        stats=[("Days to go", "184"), ("Budget", "$18k"), ("Vendors", "2/4"), ("Guests", "18")],
        nav_icons=["💒", "💰", "📋", "👥", "📅"],
        accent_cycle=["navy", "teal", "orange", "teal"],
    ),
    # --- P0007 Baby Tracker & Postpartum App ---
    "cf-q1d4697v": Dashboard(
        app_title="Baby Tracker",
        subtitle="Today · 3 feeds · 8 diapers",
        caption="Feeding, sleep, diapers — in one place",
        stats=[("Feeds today", "3"), ("Sleep hours", "7.5"), ("Diapers", "8"), ("Mood", "😊")],
        nav_icons=["📊", "🍼", "😴", "🧷", "⭐"],
    ),
    # --- P0008 Homeschool Planner App ---
    "cf-ta6u0cjs": Dashboard(
        app_title="Homeschool",
        subtitle="2 kids · 7 subjects · 3 assignments",
        caption="Children, subjects, lessons — organized",
        stats=[("Children", "2"), ("Subjects", "7"), ("This week", "8"), ("Pending", "3")],
        nav_icons=["📊", "👧", "📚", "📅", "✏️"],
        accent_cycle=["teal", "navy", "orange", "navy"],
    ),
    # --- P0009 Pet Care Organizer App ---
    "cf-eog81o2l": Dashboard(
        app_title="Pet Care",
        subtitle="2 pets · next vet in 7 days",
        caption="Vets, meds, grooming — scheduled",
        stats=[("Pets", "2"), ("Meds due", "1"), ("Next vet", "7d"), ("Groom", "Sat")],
        nav_icons=["🐾", "💊", "🍽️", "🏥", "📅"],
        accent_cycle=["teal", "orange", "navy", "teal"],
    ),
    # --- P0010 Meal Planner & Grocery App ---
    "cf-ex31190f": Dashboard(
        app_title="Meals",
        subtitle="This week · 14 meals · $125",
        caption="Recipes, meals, groceries — planned",
        stats=[("Meals", "14"), ("Recipes", "12"), ("Grocery", "23"), ("Budget", "$125")],
        nav_icons=["🍽️", "📖", "🛒", "👨‍👩‍👧", "📅"],
    ),
    # --- P0011 Moving Day Organizer App ---
    "cf-ujpf3au3": Dashboard(
        app_title="Moving",
        subtitle="45 days · 42% packed",
        caption="Packing, utilities, addresses — tracked",
        stats=[("Days out", "45"), ("Packed", "42%"), ("Rooms", "6"), ("Utilities", "5")],
        nav_icons=["📦", "🏠", "⚡", "✉️", "📅"],
        accent_cycle=["orange", "teal", "navy", "teal"],
    ),
    # --- P0012 Travel Planner App ---
    "cf-6juuqoo9": Dashboard(
        app_title="Paris · Aug 5",
        subtitle="12 days out · 68% packed",
        caption="Itinerary, packing, budget — booked",
        stats=[("Days out", "12"), ("Budget", "$2,400"), ("Packing", "68%"), ("Activities", "14")],
        nav_icons=["✈️", "🗺️", "🏨", "👜", "💰"],
        accent_cycle=["teal", "orange", "navy", "teal"],
    ),
}


GENERIC = Dashboard(
    app_title="Dashboard",
    subtitle="Today · everything in one place",
    caption="Plan, track, and share — in one place",
    stats=[("Active", "5"), ("Today", "3"), ("This week", "12"), ("Saved", "✓")],
)


def for_slug(slug: str) -> Dashboard:
    return DASHBOARDS.get(slug, GENERIC)
