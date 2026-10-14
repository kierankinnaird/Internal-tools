TRADES = ["P/Fitter", "Rigger", "Plater", "Welder", "Painter", "Inst. Tech.", "Elec. Tech.",
          "Vendor/Specialist", "Scaffolder", "Platform Ops", "RAT", "Inst.P/Fitter", "Loler"]

# Every new jobcard starts with these two tasks (quantity 1, norm 1, factor 1). They can be edited but not removed or
# moved: the "first" one stays at the top and the "last" one stays at the bottom, whatever is added between.
STANDARD_BASIS = "Standard task"
STANDARD_TASKS = [
    {"role": "first", "description": "Raise PTW, Carry out TBT, Erect Signs & Barriers"},
    {"role": "last", "description": "Complete this jobcard"},
]

FLAG_GROUPS = [
    ("Safety", ["Working at height", "Over the side work", "Rope access", "Rigging / Lifting",
                "On site LOLER plan", "Manual handling", "Other"]),
    ("Permits and hazards", ["Hot work naked flame", "Hot work (spark potential)", "Cold work",
                             "Confined space", "COSHH", "HAVS", "Subsea"]),
    ("Requirements", ["Operations", "Shutdown requirement", "Electrical/Inst isolations",
                      "Breaking containment", "High voltage", "Scaffolding", "Bolt tensioning/torqueing"]),
]
ALL_FLAGS = [f for _, fl in FLAG_GROUPS for f in fl]
