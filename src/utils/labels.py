import re
from typing import Any

from src.services.catalog.categories.l3_registry import TENNIS_SHOE_L3_VALUES

# Канонические значения gender, которые хранятся в БД.
GENDER_CANONICAL: frozenset[str] = frozenset(
    {"unisex", "men", "women", "boys", "girls", "kids"}
)

# Алиасы из фида/импорта - канон.
_GENDER_ALIASES: dict[str, str] = {
    "man": "men",
    "male": "men",
    "mens": "men",
    "men's": "men",
    "woman": "women",
    "female": "women",
    "womens": "women",
    "women's": "women",
    "boy": "boys",
    "girl": "girls",
    "kid": "kids",
    "junior": "kids",
    "children": "kids",
    "child": "kids",
    "other": "unisex",
    "all": "unisex",
    "any": "unisex",
}

# Подписи канонов для UI.
GENDER_LABELS_RU: dict[str, str] = {
    "unisex": "Для всех",
    "men": "Мужской",
    "women": "Женский",
    "boys": "Для мальчиков",
    "girls": "Для девочек",
    "kids": "Детский",
}

# Top-категории (sport_type) — ключи как в БД.
SPORT_TYPE_LABELS_RU: dict[str, str] = {
    "All": "Все",
    "Padel": "Падел",
    "Tennis": "Теннис",
    "Running": "Бег",
    "Accessories": "Аксессуары",
    "Training": "Тренировка",
    "Lifestyle": "Лайфстайл",
    "Outdoor": "Активный отдых",
    "Pickleball": "Пиклебол",
    "Tischtennis": "Настольный теннис",
}

# Подкатегории category_l2 — ключи как в БД / фиде.
CATEGORY_L2_LABELS_RU: dict[str, str] = {
    "Accessories": "Аксессуары",
    "Allround rackets": "Универсальные ракетки",
    "Backpacks": "Рюкзаки",
    "Bags": "Сумки",
    "Bandages": "Бинты и бандажи",
    "Control rackets": "Контрольные ракетки",
    "Fitness accessories": "Аксессуары для фитнеса",
    "Giant balls": "Гигантские мячи",
    "Gloves": "Перчатки",
    "Gym bags": "Сумки для зала",
    "Headgear": "Головные уборы",
    "Jackets": "Куртки",
    "Outerwear": "Верхняя одежда",
    "Overgrips": "Овергрипы",
    "Padel accessories": "Аксессуары для падела",
    "Padel bags": "Сумки для падела",
    "Padel balls": "Мячи для падела",
    "Padel racket": "Ракетки для падела",
    "Padel rackets": "Ракетки для падела",
    "Padel shoes": "Обувь для падела",
    "Power rackets": "Мощные ракетки",
    "Racket accessories": "Аксессуары для ракеток",
    "Racket bags": "Чехлы и сумки",
    "Replacement grips": "Базовые гриппы",
    "Running apparel": "Беговая одежда",
    "Running belts": "Пояса для бега",
    "Running clothes": "Беговая одежда",
    "Running shoes": "Беговая обувь",
    "Scarves": "Шарфы",
    "Shoe accessories": "Аксессуары для обуви",
    "Shoes": "Обувь",
    "Socks": "Носки",
    "String reels": "Катушки струн",
    "String sets": "Наборы струн",
    "Swimwear": "Купальники",
    "Sports bags": "Спортивные сумки",
    "Technical equipment": "Техническое оборудование",
    "Tennis balls": "Мячи для тенниса",
    "Tennis rackets": "Теннисные ракетки",
    "Tennis shoes": "Обувь для тенниса",
    "Underwear": "Спортивное бельё",
    "Wristbands": "Напульсники",
    "Books, DVD’s, magazines": "Книги и журналы",
    "Coach equipment": "Инвентарь для тренера",
    "Compression": "Компрессионная одежда",
    "Court equipment": "Инвентарь для корта",
    "Dresses": "Платья",
    "Gifts": "Подарки",
    "Hoodies & Sweaters": "Толстовки и свитеры",
    "Junior rackets": "Детские ракетки",
    "Padel clothing": "Другая одежда",
    "Pants": "Брюки",
    "Pickleball": "Пиклебол",
    "Running accessories": "Аксессуары для бега",
    "Shirts": "Футболки и топы",
    "Shorts": "Шорты",
    "Skirts": "Юбки",
    "Sports Bras": "Спортивные топы",
    "Tops": "Топы",
    "Tour rackets": "Туровые ракетки",
    "Towels": "Полотенца",
    "Tracksuits": "Спортивные костюмы",
    "Trainers": "Кроссовки",
    "Training accessories": "Тренировочные аксессуары",
    "Ball machines": "Теннисные пушки",
    "Coaching equipment": "Инвентарь для тренера",
    "Grips": "Грипсы",
    "ITF-approved": "Одобрено ITF",
    "Play & Stay": "Играй и оставайся",
    "Practice balls": "Тренировочные мячи",
    "Pressureless balls": "Мячи без давления",
    "Regular balls": "Игровые мячи",
    "Shoe bags": "Сумки для обуви",
    "Stringing machines": "Стринг-машины",
    "Table tennis": "Настольный теннис",
    "Travel bags": "Дорожные сумки",
    "ÖTV tournament balls": "Турнирные мячи",
}

# Подтипы category_l3 — ключи как в БД / GraphQL collections.
CATEGORY_L3_LABELS_RU: dict[str, str] = {
    "Advanced rackets": "Прогрессирующие",
    "All court shoes": "Кроссовки для всех покрытий",
    "Allround running shoes": "Универсальные кроссовки",
    "Ball clips": "Держатели для мячей",
    "Balls": "Мячи",
    "Bandages & tapes": "Компрессия и поддержка",
    "Basic grips": "Базовые гриппы",
    "Baskets and buckets": "Корзины и вёдра",
    "Beginner rackets": "Для начинающих",
    "Beanie": "Шапки",
    "Books, DVDs & Magazines": "Книги и журналы",
    "Ball shorts": "Игровые шорты",
    "Bandanas": "Банданы",
    "Boxer shorts": "Боксеры",
    "Capri pants": "Капри",
    "Caps & Visors": "Кепки и козырьки",
    "Carpet shoes": "Кроссовки для ковра",
    "Clay court shoes": "Кроссовки для грунта",
    "Competition running shoes": "Соревновательные кроссовки",
    "Cosmetic bags": "Косметички",
    "Dampeners": "Виброгасители",
    "Equipment": "Оборудование",
    "Elasto-cross": "Эласто-крест",
    "Flip flops": "Сланцы",
    "Frame protection": "Защита рамы",
    "Fun items": "Развлекательные товары",
    "Grips": "Грипсы",
    "Grommets": "Люверсы",
    "Grass court shoes": "Кроссовки для травы",
    "Gloves": "Перчатки",
    "Headphones": "Наушники",
    "Headwear": "Головные уборы",
    "Headbands": "Повязки на голову",
    "Hydration systems": "Системы гидратации",
    "Keychains": "Брелоки",
    "Laptop bags": "Сумки для ноутбука",
    "Lead tape": "Свинцовая лента",
    "Lines & Accessories": "Линии и аксессуары",
    "Lighting": "Освещение",
    "Hair bands": "Резинки для волос",
    "High Socks": "Высокие носки",
    "Hoodies": "Худи",
    "Leggings": "Леггинсы",
    "Long sleeve": "С длинным рукавом",
    "Mid-calf socks": "Носки до середины голени",
    "Nets & Accessories": "Сетки и аксессуары",
    "Neckwarmer": "Шейные повязки",
    "Panties": "Трусы",
    "Polos": "Поло",
    "Racket covers": "Чехлы для ракеток",
    "Recovery shoes": "Обувь для восстановления",
    "Shoelaces": "Шнурки",
    "Shoe bags": "Сумки для обуви",
    "Running belts & backpacks": "Пояса и рюкзаки",
    "Scoreboards": "Табло",
    "Running jackets & vests": "Куртки и жилеты",
    "Running pants & tights": "Брюки и тайтсы",
    "Running socks": "Беговые носки",
    "Running tops": "Беговые футболки и топы",
    "Short socks": "Короткие носки",
    "Slipover": "Слипоны",
    "Slips": "Трусы",
    "Sneakers": "Кроссовки",
    "Slippers": "Тапочки",
    "Stencil": "Трафарет",
    "Spikes": "Шиповки",
    "Sports Bras": "Спортивные топы",
    "Strings": "Стринги",
    "Sweat jackets": "Толстовки на молнии",
    "Sweatshirts": "Свитшоты",
    "T-Shirts": "Футболки",
    "Targets & Lines": "Мишени и линии",
    "Teaching tools": "Методические пособия",
    "Tournament rackets": "Профессиональные",
    "Training equipment": "Тренировочное оборудование",
    "Tracksuit bottoms": "Спортивные брюки",
    "Vests": "Жилеты",
    "Windbreaks": "Ветрозащита",
    "_no_l3_": "Прочее",
    "Trail running shoes": "Кроссовки для трейла",
    "Training jackets": "Тренировочные куртки",
    "Underwear": "Спортивное бельё",
    "Useful items & care": "Полезные мелочи и уход",
    "Wallets": "Кошельки",
    "Water bottles": "Бутылки для воды",
    "Wristbands": "Напульсники",
    "Insoles": "Стельки",
}

# Характеристики товара (ключи как в фиде supplier-demo).
FEATURE_NAME_LABELS_RU: dict[str, str] = {
    "Weight": "Вес",
    "Balance": "Баланс",
    "Material": "Материал",
    "Shape": "Форма",
    "Level": "Уровень",
    "Technology": "Технология",
    "Profile": "Профиль",
    "Frame": "Рама",
    "Surface": "Покрытие",
    "Sole": "Подошва",
    "Upper material": "Материал верха",
    "Cushioning": "Амортизация",
    "Drop": "Перепад",
    "Grip size": "Размер grip",
    "String pattern": "Схема струн",
    "Head size": "Площадь головы",
    "Length": "Длина",
    "Width": "Ширина",
    "Height": "Высота",
    "Color": "Цвет",
    "Colour": "Цвет",
    "Size": "Размер",
    "Outer material": "Материал верха",
    "Inner material": "Материал подкладки",
    "Outsole": "Подошва",
    "Court type": "Тип обуви",
    "Racket Type": "Тип ракетки",
    "Model worn size": "Размер на модели",
    "Sustainability": "Экологичность",
    "Elastic": "Эластичность",
    "easy to clean": "Лёгкий уход",
    "moisture regulating": "Влагоотведение",
    "Bag Compartments": "Отделения",
    "Dimensions (mm)": "Размеры (мм)",
    "Thermoguard": "Термозащита",
    "Packaging unit": "Единица упаковки",
    "Arm Protection": "Защита от вибраций",
    "Spin": "Вращение",
    "Game Strength": "Уровень игры",
    "Control": "Контроль",
    "Bag Capacity": "Вместимость",
    "Core material": "Материал сердечника",
    "Game type": "Тип игры",
    "Impact surface material": "Материал ударной поверхности",
    "Separate shoe compartment": "Отдельное отделение для обуви",
}

_COLOR_ALIASES: dict[str, str] = {
    "weiß": "white",
    "weiss": "white",
    "schwarz": "black",
    "grau": "grey",
    "rot": "red",
    "violett": "violet",
    "anthrazit": "anthracite",
    "nachtblau": "dark blue",
    "dunkelgrün": "dark green",
    "dunkelgruen": "dark green",
    "kobaltblau": "cobalt blue",
    "graugrün": "grey-green",
    "graugruen": "grey-green",
    "rotorange": "red-orange",
    "lavendel": "lavender",
}

COLOR_VALUE_LABELS_RU: dict[str, str] = {
    "black": "чёрный",
    "white": "белый",
    "red": "красный",
    "blue": "синий",
    "green": "зелёный",
    "yellow": "жёлтый",
    "orange": "оранжевый",
    "pink": "розовый",
    "purple": "фиолетовый",
    "violet": "фиолетовый",
    "grey": "серый",
    "gray": "серый",
    "brown": "коричневый",
    "beige": "бежевый",
    "navy": "тёмно-синий",
    "silver": "серебристый",
    "gold": "золотой",
    "cyan": "голубой",
    "lime": "лаймовый",
    "multicolor": "разноцветный",
    "multicoloured": "разноцветный",
    "multi": "разноцветный",
    "anthracite": "антрацит",
    "antique pink": "античный розовый",
    "apricot": "абрикосовый",
    "berry": "ягодный",
    "blue grey": "серо-голубой",
    "blue-gray": "серо-голубой",
    "bronze": "бронзовый",
    "caramel": "карамельный",
    "cobalt blue": "кобальтовый",
    "coral": "коралловый",
    "cream": "кремовый",
    "dark blue": "тёмно-синий",
    "dark green": "тёмно-зелёный",
    "dark grey": "тёмно-серый",
    "dark red": "тёмно-красный",
    "ecru": "экрю",
    "golden yellow": "золотисто-жёлтый",
    "grey-green": "серо-зелёный",
    "khaki": "хаки",
    "lavender": "лавандовый",
    "lemon": "лимонный",
    "light blue": "голубой",
    "light green": "светло-зелёный",
    "lightgrey": "светло-серый",
    "lightred": "светло-красный",
    "lilac": "сиреневый",
    "matte black": "матовый чёрный",
    "mauve": "лиловый",
    "mint": "мятный",
    "neon blue": "неоново-синий",
    "neon green": "неоново-зелёный",
    "neon orange": "неоново-оранжевый",
    "neon pink": "неоново-розовый",
    "neon red": "неоново-красный",
    "neon yellow": "неоново-жёлтый",
    "off white": "молочный",
    "olive": "оливковый",
    "petrol": "бирюзовый",
    "red-orange": "красно-оранжевый",
    "rose": "розовый",
    "rust": "ржавый",
    "sage": "шалфейный",
    "sand": "песочный",
    "shiny black": "глянцевый чёрный",
    "transparent": "прозрачный",
    "turquoise": "бирюзовый",
    "wine red": "бордовый",
    "pastel pink": "пастельно-розовый",
    "teal": "бирюзовый",
    "midnight blue": "полуночно-синий",
    "graublau": "серо-голубой",
    "white aluminum": "белый алюминий",
    "rose gold": "розово-золотой",
}

MATERIAL_VALUE_LABELS_RU: dict[str, str] = {
    "textile": "текстиль",
    "textil": "текстиль",
    "synthetic": "синтетика",
    "polyester": "полиэстер",
    "recycled polyester": "переработанный полиэстер",
    "mesh": "сетка",
    "tpu": "TPU",
    "eva": "EVA",
    "leather": "кожа",
    "synthetic leather": "искусственная кожа",
    "polyamide": "полиамид",
    "polyamid": "полиамид",
    "polyurethane (pu)": "полиуретан (PU)",
    "polyurethane": "полиуретан",
    "nylon": "нейлон",
    "cotton": "хлопок",
    "organic cotton": "органический хлопок",
    "elastane": "эластан",
    "elasthan": "эластан",
    "polypropylene": "полипропилен",
    "latex": "латекс",
    "rubber": "резина",
    "recyceltes": "переработанный",
    "recycled": "переработанный",
    "tpr (thermoplastics)": "TPR",
    "polyethylene": "полиэтилен",
    "wool": "шерсть",
    "lyocell": "лиоцелл",
    "modal": "модал",
    "polyacrylic": "полиакрил",
    "acryl": "акрил",
    "polytetrafluorethylen": "политетрафторэтилен",
    "elastomultiester": "эластомультиэстер",
    "viscose": "вискоза",
    "silikon": "силикон",
    "kapok": "капок",
    "alpaca": "альпака",
    "cupro": "купро",
    "elastodiene": "эластодиен",
    "pvc": "ПВХ",
    "flax": "лён",
    "hard eva": "твёрдый EVA",
    "cork": "пробка",
    "plastic": "пластик",
    "kunststoff": "пластик",
    "veloursleder": "замша",
    "phylon": "филон",
    "fiberglass": "стекловолокно",
    "carbon": "карбон",
    "2d carbon": "2D карбон",
    "12k carbon": "карбон 12K",
    "merino": "меринос",
    "merino blend": "смесь мериноса",
}

_COUNT_FEATURE_NAMES = frozenset(
    {
        "bag compartments",
        "packaging unit",
        "thermoguard",
    }
)

COURT_TYPE_VALUE_LABELS_RU: dict[str, str] = {
    "Neutral running shoe": "Нейтральные кроссовки",
    "Trail running shoe": "Трейл-кроссовки",
    "Padel shoe": "Обувь для падела",
    "Stability running shoe": "Кроссовки с поддержкой",
    "Competition running shoe": "Соревновательные кроссовки",
    "Recovery shoe": "Обувь для восстановления",
    "Spike shoes": "Шиповки",
    "Barfußschuh": "Босоногая обувь",
}

CUSHIONING_VALUE_LABELS_RU: dict[str, str] = {
    "minimal": "Минимальная",
    "very little": "Очень низкая",
    "little": "Низкая",
    "medium": "Средняя",
    "much": "Высокая",
    "very much": "Очень высокая",
    "maximum": "Максимальная",
}

ARM_PROTECTION_VALUE_LABELS_RU: dict[str, str] = {
    "light": "Лёгкая",
    "medium": "Средняя",
    "high": "Высокая",
}

SPIN_VALUE_LABELS_RU: dict[str, str] = {
    "little": "Низкое",
    "medium": "Среднее",
    "a lot of": "Высокое",
}

CONTROL_VALUE_LABELS_RU: dict[str, str] = {
    "minimal": "Минимальный",
    "medium": "Средний",
    "maximum": "Максимальный",
}

GAME_STRENGTH_PLAYER_LABELS_RU: dict[str, str] = {
    "club player": "Клубный уровень",
    "tournament player": "Турнирный уровень",
    "beginners": "Для начинающих",
}

GAME_TYPE_VALUE_LABELS_RU: dict[str, str] = {
    "control": "Контроль",
    "power": "Мощность",
}

_MATERIAL_FEATURE_NAMES = frozenset(
    {
        "outer material",
        "inner material",
        "outsole",
        "sustainability",
        "elastic",
        "easy to clean",
        "moisture regulating",
        "material",
        "core material",
        "impact surface material",
    }
)

OPTION_VALUE_LABELS_RU: dict[str, str] = {
    "nosize": "Без размера",
    "no size": "Без размера",
    "no-size": "Без размера",
    "one size": "Универсальный",
    "one-size": "Универсальный",
    "full-surface": "Полная поверхность",
    "full surface": "Полная поверхность",
    "default title": "Стандарт",
    "unstrung": "Без струн",
    "strung": "Со струнами",
}

# Базовые L2 для теннисной обуви (родитель подтипов l3).
TENNIS_SHOES_BASE_L2: tuple[str, ...] = ("Tennis shoes", "Shoes")

# Подтипы теннисной обуви, которые иногда попадают в category_l2 вместо l3.
TENNIS_SHOE_SUBTYPE_L3 = TENNIS_SHOE_L3_VALUES

# Все L2, где option2 — EU-размер обуви (источник правды для сортировки на PDP).
FOOTWEAR_CATEGORY_L2: frozenset[str] = frozenset(
    {
        *TENNIS_SHOES_BASE_L2,
        *TENNIS_SHOE_SUBTYPE_L3,
        "Running shoes",
        "Padel shoes",
        "Trainers",
    }
)


# Проверяет, что товар относится к обуви (L2 или L3 в FOOTWEAR_CATEGORY_L2).
def is_footwear_category(
    category_l2: str | None,
    category_l3: str | None = None,
) -> bool:
    if category_l2 and category_l2 in FOOTWEAR_CATEGORY_L2:
        return True
    if category_l3 and category_l3 in FOOTWEAR_CATEGORY_L2:
        return True
    return False


# Синонимы category_l2 из фида → канонический ключ в БД.
CATEGORY_L2_CANONICAL: dict[str, str] = {
    "Padel racket": "Padel rackets",
}

RACKET_CATEGORY_L2: frozenset[str] = frozenset(
    {
        "Padel rackets",
        "Tennis rackets",
        "Junior rackets",
        "Allround rackets",
        "Control rackets",
        "Power rackets",
        "Tour rackets",
    }
)

PADEL_RACKET_L2: frozenset[str] = frozenset({"Padel rackets", "Padel racket"})

_STRINGING_OPTION_VALUES: frozenset[str] = frozenset({"unstrung", "strung"})
_SURFACE_OPTION_VALUES: frozenset[str] = frozenset({"full-surface", "full surface"})
_GRIP_SIZE_OPTION_VALUES: frozenset[str] = frozenset(
    {"0", "1", "2", "3", "4", "000", "00", "0000"}
)

_PRODUCT_TYPE_SUFFIX_RES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\s+(?:"
        r"padel|tennis|running|trail|stability|neutral|competition|recovery"
        r")\s+(?:"
        r"rackets?|balls?|shoes?|shoe|apparel|clothes|belts|bags?|accessories?|clothing"
        r")\b.*$",
        re.IGNORECASE,
    ),
    re.compile(r"\s+running\s+shoe\b.*$", re.IGNORECASE),
    re.compile(r"\s+padel\s+shoe\b.*$", re.IGNORECASE),
    re.compile(r"\s+tennis\s+shoe\b.*$", re.IGNORECASE),
)


# Переводит текст состава материалов на русский язык.
def _translate_composition_text(text: str) -> str:
    translated = text
    for eng, ru in sorted(MATERIAL_VALUE_LABELS_RU.items(), key=lambda x: -len(x[0])):
        translated = re.sub(re.escape(eng), ru, translated, flags=re.IGNORECASE)
    return translated


# Проверяет, относится ли категория к ракетке.
def _is_racket_category(category_l2: str | None) -> bool:
    cat = (category_l2 or "").strip()
    if cat in RACKET_CATEGORY_L2:
        return True
    return "racket" in cat.lower()


# Нормализует значение поверхности ракетки для сравнения.
def _normalize_surface_value(value: str) -> str:
    return str(value or "").strip().lower().replace("-", " ")


# True, если у падел-ракетки единственная опция поверхности — full-surface.
def is_redundant_surface_option(
    category_l2: str | None,
    option_key: str,
    option_values: list[str] | tuple[str, ...] | None,
) -> bool:
    cat = (category_l2 or "").strip()
    canonical = CATEGORY_L2_CANONICAL.get(cat, cat)
    if canonical not in PADEL_RACKET_L2 and cat not in PADEL_RACKET_L2:
        return False
    if option_key != "option1" or not option_values:
        return False
    distinct: list[str] = []
    seen: set[str] = set()
    for raw in option_values:
        text = str(raw or "").strip()
        if not text:
            continue
        normalized = _normalize_surface_value(text)
        if normalized in seen:
            continue
        seen.add(normalized)
        distinct.append(normalized)
    if len(distinct) != 1:
        return False
    return distinct[0] == "full surface"


# Нормализует значения опций.
def _normalize_option_values(values: list[str] | tuple[str, ...] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    for value in values:
        text = str(value or "").strip().lower()
        if text:
            out.append(text)
    return out


# Определяет русскую подпись опции варианта товара.
def resolve_variant_option_label(
    option_key: str,
    *,
    category_l2: str | None = None,
    option_values: list[str] | tuple[str, ...] | None = None,
) -> str:
    values = _normalize_option_values(option_values)
    is_racket = _is_racket_category(category_l2)

    if option_key == "option1":
        if not values:
            return "Опция"
        if is_racket:
            if all(v in _STRINGING_OPTION_VALUES for v in values):
                return "Струны"
            if all(
                v in _SURFACE_OPTION_VALUES
                or v.replace("-", " ") in _SURFACE_OPTION_VALUES
                for v in values
            ):
                return "Поверхность"
            if all(_looks_like_color_value(v) for v in values):
                return "Цвет"
            return "Опция"
        if all(_looks_like_color_value(v) for v in values):
            return "Цвет"
        return "Опция"

    if option_key == "option2":
        if is_racket and values:
            if all(v in _GRIP_SIZE_OPTION_VALUES for v in values):
                return "Размер grip"
        return "Размер"

    if option_key == "option3":
        return "Опция 3"
    return "Опция"


# Переводит название признака на русский язык.
def translate_feature_name(value: str | None) -> str:
    if not value:
        return ""
    key = value.strip()
    return FEATURE_NAME_LABELS_RU.get(key, key)


# Нормализует ключ цвета.
def _normalize_color_key(token: str) -> str:
    key = token.strip().lower().replace("-", " ")
    if not key:
        return ""
    return _COLOR_ALIASES.get(key, key)


# Ищет русское название цвета по ключу.
def _color_lookup(key: str) -> str | None:
    if not key:
        return None
    for candidate in (key, key.replace(" ", "-"), key.replace(" ", "")):
        if candidate in COLOR_VALUE_LABELS_RU:
            return COLOR_VALUE_LABELS_RU[candidate]
    return None


# Переводит токен цвета на русский язык.
def _translate_color_token(token: str) -> str:
    key = _normalize_color_key(token)
    if not key:
        return token.strip()
    translated = _color_lookup(key)
    return translated if translated is not None else token.strip()


# Переводит значение цвета на русский язык.
def translate_color_value(value: str) -> str:
    parts = [p.strip() for p in re.split(r"[,/|]", value) if p.strip()]
    if not parts:
        return value.strip()
    return ", ".join(_translate_color_token(part) for part in parts)


# Переводит токен материала на русский язык.
def _translate_material_token(token: str) -> str:
    key = token.strip().lower()
    if not key:
        return token.strip()
    if key in MATERIAL_VALUE_LABELS_RU:
        return MATERIAL_VALUE_LABELS_RU[key]
    return token.strip()


# Переводит количество признака на русский язык.
def _ru_plural(n: int, one: str, few: str, many: str) -> str:
    mod100 = abs(n) % 100
    mod10 = mod100 % 10
    if 11 <= mod100 <= 19:
        return many
    if mod10 == 1:
        return one
    if 2 <= mod10 <= 4:
        return few
    return many


# Переводит количество признака на русский язык.
def _translate_count_feature_value(name_key: str, text: str) -> str | None:
    if not text.isdigit():
        return None
    count = int(text)
    if name_key == "bag compartments":
        word = _ru_plural(count, "отделение", "отделения", "отделений")
        return f"{count} {word}"
    if name_key == "packaging unit":
        return f"{count} {_ru_plural(count, 'шт.', 'шт.', 'шт.')}"
    if name_key == "thermoguard":
        return f"Уровень {count}"
    return None


# Переводит размер на модели на русский язык.
def _translate_model_worn_size(value: str) -> str:
    text = translate_measurement_value(value)
    return re.sub(r"\bsize\b", "размер", text, flags=re.IGNORECASE)


# Переводит значение материала на русский язык.
def translate_material_value(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if _looks_like_color_value(text):
        return translate_color_value(text)
    if text in COURT_TYPE_VALUE_LABELS_RU:
        return COURT_TYPE_VALUE_LABELS_RU[text]
    if "%" in text:
        return _translate_composition_text(text)
    parts = [p.strip() for p in re.split(r"[,/|]", text) if p.strip()]
    if len(parts) > 1:
        composed = ", ".join(_translate_material_token(part) for part in parts)
        if composed != text:
            return composed
        return _translate_composition_text(text)
    lowered = text.lower()
    if lowered in MATERIAL_VALUE_LABELS_RU:
        return MATERIAL_VALUE_LABELS_RU[lowered]
    return _translate_composition_text(text)


# Проверяет, похоже ли значение на цвет.
def _looks_like_color_value(raw: str) -> bool:
    key = raw.strip().lower()
    if not key:
        return False
    if key in OPTION_VALUE_LABELS_RU:
        return False
    if "," in raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return bool(parts) and all(_is_color_token(p) for p in parts)
    return _is_color_token(key)


# Проверяет, является ли токен цветом.
def _is_color_token(token: str) -> bool:
    key = _normalize_color_key(token)
    if not key:
        return False
    if key in OPTION_VALUE_LABELS_RU:
        return False
    return _color_lookup(key) is not None


# Удаляет суффикс цвета из названия.
def _strip_color_suffix_from_title(title: str) -> str:
    result = title.strip()
    if not result:
        return result
    for pattern in (
        r"\s[-–—]\s*(.+)$",
        r"[-–—]([^-–—/]+)$",
    ):
        match = re.search(pattern, result, flags=re.IGNORECASE)
        if not match:
            continue
        tail = match.group(1).strip()
        if _looks_like_color_value(tail):
            result = result[: match.start()].strip()
            break
    return result


# Переводит значение веса на русский язык.
def translate_weight_value(value: str) -> str:
    text = value.strip()

    def repl(match: re.Match[str]) -> str:
        return f"{match.group(1)} г"

    return re.sub(
        r"(\d+(?:[.,]\d+)?)\s*(?:g|gr|gram|grams)\b", repl, text, flags=re.IGNORECASE
    )


_MEASUREMENT_IN_TEXT_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:mm\b|cm(?:²|2|\^2|\b)|m\b)",
    re.IGNORECASE,
)

_BAG_CAPACITY_RE = re.compile(r"^(\d+)-(\d+)\s+tennis rackets$", re.IGNORECASE)


# Переводит значение типа обуви с fallback на category_l3.
def _translate_court_type_value(text: str) -> str:
    direct = COURT_TYPE_VALUE_LABELS_RU.get(text)
    if direct is not None:
        return direct
    l3_key = text
    if text.endswith(" shoe") and not text.endswith(" shoes"):
        l3_key = f"{text[:-5]} shoes"
    l3_label = CATEGORY_L3_LABELS_RU.get(l3_key)
    if l3_label is not None:
        return l3_label
    return text


# Переводит уровень игры (список типов игроков).
def _translate_game_strength_value(text: str) -> str:
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return text
    translated = [
        GAME_STRENGTH_PLAYER_LABELS_RU.get(part.lower(), part) for part in parts
    ]
    return ", ".join(translated)


# Переводит вместимость сумки в число ракеток.
def _translate_bag_capacity_value(text: str) -> str:
    match = _BAG_CAPACITY_RE.match(text.strip())
    if not match:
        return text
    return f"{match.group(1)}–{match.group(2)} ракеток"


# Переводит значение измерения на русский язык.
def translate_measurement_value(value: str) -> str:
    text = translate_weight_value(value.strip())
    text = re.sub(
        r"(\d+(?:[.,]\d+)?)\s*mm\b",
        r"\1 мм",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(\d+(?:[.,]\d+)?)\s*cm\s*(?:²|2|\^2)",
        r"\1 см²",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(\d+(?:[.,]\d+)?)\s*cm\b",
        r"\1 см",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(\d+(?:[.,]\d+)?)\s*m\b",
        r"\1 м",
        text,
        flags=re.IGNORECASE,
    )
    return text


# Переводит значение признака на русский язык.
def translate_feature_value(name: str | None, value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    if not text:
        return ""
    name_key = (name or "").strip().lower()
    if name_key in {"colour", "color", "цвет"}:
        return translate_color_value(text)
    if name_key in {"court type"}:
        return _translate_court_type_value(text)
    if name_key in {"cushioning", "амортизация"}:
        return CUSHIONING_VALUE_LABELS_RU.get(text.lower(), text)
    if name_key in {"arm protection"}:
        return ARM_PROTECTION_VALUE_LABELS_RU.get(text.lower(), text)
    if name_key in {"spin"}:
        return SPIN_VALUE_LABELS_RU.get(text.lower(), text)
    if name_key in {"control"}:
        return CONTROL_VALUE_LABELS_RU.get(text.lower(), text)
    if name_key in {"game strength"}:
        return _translate_game_strength_value(text)
    if name_key in {"game type"}:
        return GAME_TYPE_VALUE_LABELS_RU.get(text.lower(), text)
    if name_key in {"bag capacity"}:
        return _translate_bag_capacity_value(text)
    if name_key in {"separate shoe compartment"}:
        return translate_color_value(text)
    if name_key in {"racket type"}:
        return OPTION_VALUE_LABELS_RU.get(text.lower(), text)
    if name_key in {"model worn size", "размер на модели"}:
        return _translate_model_worn_size(text)
    if name_key in _COUNT_FEATURE_NAMES:
        translated = _translate_count_feature_value(name_key, text)
        if translated is not None:
            return translated
    if name_key in _MATERIAL_FEATURE_NAMES:
        if name_key == "sustainability" and text.lower() == "maximum":
            return "Максимальная"
        return translate_material_value(text)
    if name_key in {"length", "длина"}:
        return translate_measurement_value(text)
    if name_key in {"weight", "вес"} or re.search(
        r"\d+(?:[.,]\d+)?\s*(?:g|gr|gram|grams)\b", text, re.IGNORECASE
    ):
        return translate_measurement_value(text)
    if name_key in {"dimensions (mm)"}:
        return translate_measurement_value(
            text.replace("Length:", "Длина:")
            .replace("Width:", "Ширина:")
            .replace("Height:", "Высота:")
        )
    if _MEASUREMENT_IN_TEXT_RE.search(text):
        return translate_measurement_value(text)
    return text


# Переводит значение опции на русский язык.
def translate_option_value(value: str | None) -> str:
    if not value:
        return ""
    raw = value.strip()
    if not raw:
        return ""
    key = raw.lower()
    if key in OPTION_VALUE_LABELS_RU:
        return OPTION_VALUE_LABELS_RU[key]
    normalized = key.replace("-", " ")
    if normalized in OPTION_VALUE_LABELS_RU:
        return OPTION_VALUE_LABELS_RU[normalized]
    if _looks_like_color_value(raw):
        return translate_color_value(raw)
    if _MEASUREMENT_IN_TEXT_RE.search(raw):
        return translate_measurement_value(raw)
    return raw


# Удаляет тип продукта из названия.
def strip_product_type_from_title(title: str | None) -> str:
    if not title:
        return ""
    result = title.strip()
    if not result:
        return ""
    prev = None
    while prev != result:
        prev = result
        for pattern in _PRODUCT_TYPE_SUFFIX_RES:
            result = pattern.sub("", result).strip()
    return result


# Формирует отображаемое название товара.
def display_product_title(
    title: str | None,
    *,
    option1: str | None = None,
    option2: str | None = None,
    option3: str | None = None,
) -> str:
    original = str(title or "").strip()
    if not original:
        return ""
    result = original
    for val in (option1, option2, option3):
        opt = str(val or "").strip()
        if not opt:
            continue
        escaped = re.escape(opt)
        for pattern in (
            rf"\s*[-–—/,|]\s*{escaped}\s*$",
            rf"\s+{escaped}\s*$",
        ):
            result = re.sub(pattern, "", result, flags=re.IGNORECASE).strip()
    result = strip_product_type_from_title(result)
    result = _strip_color_suffix_from_title(result)
    return result or original


# Эвристика по title GraphQL/листинга (Women/Men/Unisex в названии).
_GENDER_TITLE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bunisex\b", re.I), "unisex"),
    (re.compile(r"\bwomen\b", re.I), "women"),
    (re.compile(r"\bmen\b", re.I), "men"),
    (re.compile(r"\bboys\b", re.I), "boys"),
    (re.compile(r"\bgirls\b", re.I), "girls"),
    (re.compile(r"\bkids\b", re.I), "kids"),
    (re.compile(r"\bjunior\b", re.I), "kids"),
)


def infer_gender_from_title(title: str | None) -> str | None:
    if not title:
        return None
    for pattern, canonical in _GENDER_TITLE_PATTERNS:
        if pattern.search(title):
            return canonical
    return None


# Приводит произвольное значение gender к канону; для незнакомого возвращает None.
def normalize_gender(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower()
    canonical = _GENDER_ALIASES.get(key, key)
    return canonical if canonical in GENDER_CANONICAL else None


# Возвращает русскую подпись gender; для пустого/неизвестного - пустую строку.
def translate_gender(value: str | None) -> str:
    if not value:
        return ""
    return GENDER_LABELS_RU.get(value, value)


# Нормализует sport_type / top-категорию из фида импорта.
def normalize_sport_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    aliases = {
        "tennis": "Tennis",
        "running": "Running",
        "padel": "Padel",
        "accessories": "Accessories",
    }
    return aliases.get(normalized, str(value).strip())


# Возвращает русскую подпись sport_type; для пустого/неизвестного — исходное значение.
def translate_sport_type(value: str | None) -> str:
    if not value:
        return ""
    key = value.strip()
    return SPORT_TYPE_LABELS_RU.get(key, key)


# Приводит category_l2 к каноническому ключу (singular → plural и т.п.).
def normalize_category_l2(value: str | None) -> str | None:
    l2, _l3 = normalize_category_levels(value, None)
    return l2


# Нормализует пару category_l2/category_l3 (подтипы обуви → Tennis shoes + l3).
def normalize_category_levels(
    category_l2: str | None,
    category_l3: str | None = None,
    *,
    sport_type: str | None = None,
) -> tuple[str | None, str | None]:
    raw_l2 = (category_l2 or "").strip() or None
    l3 = (category_l3 or "").strip() or None
    if raw_l2:
        raw_l2 = CATEGORY_L2_CANONICAL.get(raw_l2, raw_l2)
    sport = (sport_type or "").strip()
    if raw_l2 in TENNIS_SHOE_SUBTYPE_L3 and sport in ("", "Tennis"):
        if not l3:
            l3 = raw_l2
        raw_l2 = "Tennis shoes"
    return raw_l2, l3


# Возвращает русскую подпись category_l2; для пустого/неизвестного — исходное значение.
def translate_category_l2(value: str | None) -> str:
    if not value:
        return ""
    key = (value or "").strip()
    if key in TENNIS_SHOE_SUBTYPE_L3:
        return translate_category_l3(key)
    key = normalize_category_l2(key) or key
    return CATEGORY_L2_LABELS_RU.get(key, CATEGORY_L3_LABELS_RU.get(key, key))


def translate_category_l3(value: str | None) -> str:
    if not value:
        return ""
    key = value.strip()
    return CATEGORY_L3_LABELS_RU.get(key, CATEGORY_L2_LABELS_RU.get(key, key))


# Подпись типа в подменю подкатегории (l2/l3 + служебный _no_l3_).
def translate_subcategory_type(value: str | None, *, type_level: str = "l2") -> str:
    key = (value or "").strip()
    if not key:
        return ""
    if key == "_no_l3_":
        return "Прочее"
    if type_level == "l3":
        return translate_category_l3(key)
    return translate_category_l2(key)


# Определяет ключ вида спорта по полям товара (как на витрине).
def resolve_sport_type_key(
    sport_type: str | None = None,
    category_l1: str | None = None,
    category_l2: str | None = None,
    category_l3: str | None = None,
) -> str:
    raw = (sport_type or category_l1 or category_l2 or category_l3 or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered == "accessories" or "accessories" in lowered.split():
        return "Accessories"
    if "padel" in lowered:
        return "Padel"
    if "tennis" in lowered:
        return "Tennis"
    if "running" in lowered:
        return "Running"
    return raw


# Подпись бейджа «вид спорта» на карточке товара.
def product_sport_badge_label_ru(
    sport_type: str | None = None,
    category_l1: str | None = None,
    category_l2: str | None = None,
    category_l3: str | None = None,
) -> str:
    key = resolve_sport_type_key(sport_type, category_l1, category_l2, category_l3)
    if not key:
        return "Товар"
    if key in SPORT_TYPE_LABELS_RU:
        return translate_sport_type(key)
    return translate_category_l2(key)


# Словари для window.__APP_CONFIG__ / GET /catalog/labels.
def catalog_labels_client_dict() -> dict[str, object]:
    return {
        "sport_types": dict(SPORT_TYPE_LABELS_RU),
        "category_l2": dict(CATEGORY_L2_LABELS_RU),
        "category_l3": dict(CATEGORY_L3_LABELS_RU),
        "genders": dict(GENDER_LABELS_RU),
        "filter_all": "Все",
        "product_fallback": "Товар",
    }
