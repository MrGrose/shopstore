import re

PADEL_L3_BEGINNER = "Beginner rackets"
PADEL_L3_ADVANCED = "Advanced rackets"
PADEL_L3_TOURNAMENT = "Tournament rackets"

PADEL_RACKET_L3_BY_HANDLE: dict[str, str] = {
    "padel-padel-racket-beginner-rackets": PADEL_L3_BEGINNER,
    "padel-padel-racket-tournament-rackets": PADEL_L3_TOURNAMENT,
    "padel-padel-racket-advanced-rackets": PADEL_L3_ADVANCED,
}

PADEL_RACKET_L3_TITLE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(junior|beginner|starter|initiation)\b", re.I), PADEL_L3_BEGINNER),
    (re.compile(r"\bclassic\b", re.I), PADEL_L3_BEGINNER),
    (re.compile(r"\b(xtreme|optimus|air)\b", re.I), PADEL_L3_ADVANCED),
    (re.compile(r"\b(tournament|tour|pro|cupra)\b", re.I), PADEL_L3_TOURNAMENT),
    (re.compile(r"\badvanced\b", re.I), PADEL_L3_ADVANCED),
)

TENNIS_SHOE_L3_ALL_COURT = "All court shoes"
TENNIS_SHOE_L3_CLAY = "Clay court shoes"
TENNIS_SHOE_L3_GRASS = "Grass court shoes"
TENNIS_SHOE_L3_CARPET = "Carpet shoes"
TENNIS_SHOE_L3_FLIP_FLOPS = "Flip flops"
TENNIS_SHOE_L3_SNEAKERS = "Sneakers"
TENNIS_SHOE_L3_SLIPPERS = "Slippers"

TENNIS_SHOE_L3_VALUES: frozenset[str] = frozenset(
    {
        TENNIS_SHOE_L3_ALL_COURT,
        TENNIS_SHOE_L3_CLAY,
        TENNIS_SHOE_L3_CARPET,
        TENNIS_SHOE_L3_GRASS,
        TENNIS_SHOE_L3_SNEAKERS,
        TENNIS_SHOE_L3_FLIP_FLOPS,
        TENNIS_SHOE_L3_SLIPPERS,
    }
)

TENNIS_SHOE_L3_BY_HANDLE_SUFFIX: dict[str, str] = {
    "all-court-shoes": TENNIS_SHOE_L3_ALL_COURT,
    "clay-court-shoes": TENNIS_SHOE_L3_CLAY,
    "carpet-shoes": TENNIS_SHOE_L3_CARPET,
    "grass-court-shoes": TENNIS_SHOE_L3_GRASS,
    "trainers": TENNIS_SHOE_L3_SNEAKERS,
    "slippers": TENNIS_SHOE_L3_FLIP_FLOPS,
}

TENNIS_SHOE_L3_TITLE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bclay[\s-]?court\b", re.I), TENNIS_SHOE_L3_CLAY),
    (re.compile(r"\ball[\s-]?court\b", re.I), TENNIS_SHOE_L3_ALL_COURT),
    (re.compile(r"\bgrass[\s-]?court\b", re.I), TENNIS_SHOE_L3_GRASS),
    (re.compile(r"\bcarpet\b", re.I), TENNIS_SHOE_L3_CARPET),
    (re.compile(r"\b(slipper|flip[\s-]?flop)\b", re.I), TENNIS_SHOE_L3_FLIP_FLOPS),
    (re.compile(r"\b(sneaker|trainer)\b", re.I), TENNIS_SHOE_L3_SNEAKERS),
)

RUNNING_L3_TRAIL = "Trail running shoes"
RUNNING_L3_COMPETITION = "Competition running shoes"
RUNNING_L3_RECOVERY = "Recovery shoes"
RUNNING_L3_SPIKES = "Spikes"
RUNNING_L3_ALLROUND = "Allround running shoes"
RUNNING_L3_SLIPPERS = "Slippers"

RUNNING_SHOE_L3_TITLE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(sandal|slipper)\b", re.I), RUNNING_L3_SLIPPERS),
    (re.compile(r"\btrail\b", re.I), RUNNING_L3_TRAIL),
    (re.compile(r"\b(competition|racing|race)\b", re.I), RUNNING_L3_COMPETITION),
    (re.compile(r"\brecovery\b", re.I), RUNNING_L3_RECOVERY),
    (re.compile(r"\bspike\b", re.I), RUNNING_L3_SPIKES),
    (
        re.compile(r"\b(neutral|allround|all[\s-]?round|stability)\b", re.I),
        RUNNING_L3_ALLROUND,
    ),
)

RACKET_L2_BY_HANDLE_SUFFIX: dict[str, str] = {
    "junior-rackets": "Junior rackets",
    "tour-rackets": "Tour rackets",
    "allround-rackets": "Allround rackets",
    "power-rackets": "Power rackets",
    "control-rackets": "Control rackets",
}
