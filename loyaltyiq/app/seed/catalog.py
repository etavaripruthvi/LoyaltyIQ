"""Catalogue generator: ~1,000 products across 16 categories.

Products are built from families (e.g. "Basmati Rice") x brands x pack sizes, with
fictional brand names, INR prices, stock levels and margins. Emojis stand in for photos."""
import math

CATEGORIES = [
    # key, display name, emoji, tile colour, replenishment cycle in days (None = durable)
    ("staples", "Staples & Grains", "🌾", "#f6e3b4", 28),
    ("produce", "Fruits & Vegetables", "🥬", "#cfeccb", 7),
    ("dairy", "Dairy & Eggs", "🥛", "#dcebfb", 6),
    ("snacks", "Snacks & Beverages", "🍿", "#fde0c4", 14),
    ("bakery", "Bakery & Breakfast", "🍞", "#f4dcc8", 8),
    ("personal_care", "Personal Care & Beauty", "🧴", "#f6d6e6", 40),
    ("home", "Home & Cleaning", "🧹", "#d7ecee", 35),
    ("baby", "Baby & Kids", "🍼", "#e7dcf7", 21),
    ("pet", "Pet Care", "🐶", "#ecdcc9", 28),
    ("kitchen", "Kitchen & Dining", "🍳", "#fbe6c9", None),
    ("electronics", "Electronics", "💻", "#d3dcf5", None),
    ("mobile", "Mobiles & Accessories", "📱", "#cfe5f2", None),
    ("games", "Games & Toys", "🎮", "#e3d5f5", None),
    ("sports", "Sports & Fitness", "🏋️", "#d4efdc", None),
    ("fashion", "Fashion & Apparel", "👕", "#fad3d3", None),
    ("books", "Books & Stationery", "📚", "#f2e8c9", None),
]
CAT_KEYS = [c[0] for c in CATEGORIES]
CAT_META = {c[0]: {"key": c[0], "name": c[1], "emoji": c[2], "color": c[3], "cycle": c[4]} for c in CATEGORIES}

# Fictional brands: (name, tier). Tier drives price level and shopper preference.
POOLS = {
    "staples": [("Annapurna Pure", "value"), ("Harvest Gold", "standard"), ("Organic Roots", "premium")],
    "produce": [("Local Fresh", "value"), ("Farm Direct", "standard"), ("Organic Valley", "premium")],
    "dairy": [("Milkways", "value"), ("Pure Pastures", "standard"), ("Alpine Creamery", "premium")],
    "snacks": [("Crunchy Corner", "value"), ("SnackBay", "standard"), ("Gourmet Lane", "premium")],
    "bakery": [("Daily Loaf", "value"), ("Oven Fresh", "standard"), ("Patisserie Royale", "premium")],
    "beauty": [("Naturelle", "value"), ("GlowCo", "standard"), ("Aurelle", "premium")],
    "home": [("CleanMate", "value"), ("HomeBright", "standard"), ("EcoNest", "premium")],
    "baby": [("TinyTots", "value"), ("Cuddle Care", "standard"), ("Little Haven", "premium")],
    "pet": [("PawPantry", "value"), ("Happy Tails", "standard"), ("Noble Beast", "premium")],
    "kitchen": [("Kitchenia", "value"), ("ChefMate", "standard"), ("Maison Cuisine", "premium")],
    "electronics": [("Voltix", "value"), ("Nexora", "standard"), ("Aurion", "premium")],
    "mobile": [("ChargeUp", "value"), ("Linkon", "standard"), ("Zenith Gear", "premium")],
    "games": [("PlayPulse", "value"), ("Nova Play", "standard"), ("Apex Interactive", "premium")],
    "sports": [("FitStart", "value"), ("ProStride", "standard"), ("Titan Athletics", "premium")],
    "fashion": [("Urban Thread", "value"), ("Stitchcraft", "standard"), ("Maison Veda", "premium")],
    "books": [("PaperPlus", "value"), ("Inkwell", "standard"), ("Classic Press", "premium")],
}
TIER_FACTOR = {"value": 0.86, "standard": 1.0, "premium": 1.32}
TIER_IDX = {"value": 0, "standard": 1, "premium": 2}

# Pack-size / variant ladders: (label, price multiplier)
SIZES = {
    "kg": [("500 g", .5), ("1 kg", 1), ("5 kg", 4.8)],
    "kg2": [("1 kg", 1), ("5 kg", 4.7)],
    "spice": [("100 g", .1), ("200 g", .2), ("500 g", .5)],
    "ghee": [("200 g", .2), ("500 g", .5), ("1 kg", 1)],
    "litre": [("500 ml", .5), ("1 L", 1), ("5 L", 4.7)],
    "prod": [("500 g", .5), ("1 kg", 1)],
    "milk": [("500 ml", .5), ("1 L", 1), ("2 L", 1.95)],
    "tub": [("200 g", .2), ("400 g", .4), ("1 kg", 1)],
    "eggs": [("6 pcs", .5), ("12 pcs", 1), ("30 pcs", 2.4)],
    "pack": [("Small pack", .6), ("Regular pack", 1), ("Family pack", 1.8)],
    "bottle": [("200 ml", .6), ("400 ml", 1), ("1 L", 2.2)],
    "jar": [("340 g", .7), ("510 g", 1), ("1 kg", 1.7)],
    "cake": [("500 g", 1), ("1 kg", 1.9)],
    "tube": [("50 g", .6), ("100 g", 1)],
    "perf": [("30 ml", .6), ("50 ml", 1), ("100 ml", 1.7)],
    "bulb": [("9 W", 1), ("12 W", 1.4), ("15 W", 1.8)],
    "bed": [("Single", .7), ("Double", 1), ("King", 1.3)],
    "dsize": [("Small", .9), ("Medium", 1), ("Large", 1.1), ("XL", 1.2)],
    "tin": [("400 g", 1), ("800 g", 1.9)],
    "kg3": [("1 kg", 1), ("3 kg", 2.7), ("10 kg", 8.5)],
    "pan": [("24 cm", 1), ("28 cm", 1.3)],
    "cooker": [("3 L", 1), ("5 L", 1.4)],
    "set": [("Starter set", 1), ("Family set", 1.7)],
    "bottle2": [("750 ml", 1), ("1 L", 1.2)],
    "model": [("Lite", .8), ("Plus", 1), ("Pro", 1.5)],
    "phone": [("64 GB", .8), ("128 GB", 1), ("256 GB", 1.3)],
    "laptop": [("8 GB / 256 GB", .9), ("16 GB / 512 GB", 1.25)],
    "tv": [("43 inch", 1), ("55 inch", 1.6)],
    "power": [("10000 mAh", 1), ("20000 mAh", 1.7)],
    "mon": [("22 inch", 1), ("27 inch", 1.6)],
    "case": [("Slim", 1), ("Rugged", 1.4)],
    "charger": [("20 W", 1), ("33 W", 1.4), ("65 W", 2.2)],
    "cable": [("1 m", 1), ("2 m", 1.4)],
    "card": [("64 GB", 1), ("128 GB", 1.6), ("256 GB", 2.6)],
    "console": [("Standard", 1), ("Pro", 1.4)],
    "platform": [("Console", 1), ("PC", .8)],
    "board": [("Classic", 1), ("Deluxe", 1.6)],
    "puz": [("500 pcs", 1), ("1000 pcs", 1.6)],
    "blocks": [("250 pcs", 1), ("600 pcs", 2.1)],
    "toy": [("Medium", 1), ("Large", 1.8)],
    "mat": [("4 mm", 1), ("6 mm", 1.3)],
    "weights": [("5 kg", .8), ("10 kg", 1.3), ("20 kg", 2.3)],
    "protein": [("1 kg", 1), ("2 kg", 1.85)],
    "tabs": [("60 tabs", 1), ("120 tabs", 1.8)],
    "fit": [("Regular", 1), ("Premium", 1.4)],
    "socks": [("3 pairs", 1), ("6 pairs", 1.8)],
    "nb": [("Pack of 3", 1), ("Pack of 6", 1.9)],
    "book": [("Paperback", 1), ("Hardcover", 1.7)],
    "one": [("Standard", 1)],
}

# Families: (name, emoji, base price at multiplier 1, size ladder, brands used)
FAMILIES = {
    "staples": [
        ("Basmati Rice", "🍚", 125, "kg2", 3), ("Sona Masoori Rice", "🍚", 66, "kg2", 2),
        ("Whole Wheat Atta", "🌾", 50, "kg2", 3), ("Toor Dal", "🫘", 158, "kg", 2),
        ("Moong Dal", "🫘", 128, "kg", 2), ("Chana Dal", "🫘", 105, "kg", 2),
        ("Sugar", "🍬", 46, "kg2", 2), ("Iodised Salt", "🧂", 24, "kg", 2),
        ("Sunflower Oil", "🌻", 142, "litre", 3), ("Cow Ghee", "🧈", 620, "ghee", 3),
        ("Turmeric Powder", "🟡", 260, "spice", 2), ("Red Chilli Powder", "🌶️", 300, "spice", 2),
        ("Tea Leaves", "🍵", 400, "spice", 3), ("Rolled Oats", "🥣", 150, "kg", 2),
    ],
    "produce": [
        ("Apples", "🍎", 190, "prod", 2), ("Bananas", "🍌", 55, "prod", 2), ("Mangoes", "🥭", 150, "prod", 2),
        ("Oranges", "🍊", 90, "prod", 2), ("Grapes", "🍇", 120, "prod", 2), ("Papaya", "🍈", 60, "prod", 2),
        ("Watermelon", "🍉", 30, "prod", 2), ("Tomatoes", "🍅", 40, "prod", 2), ("Onions", "🧅", 36, "prod", 2),
        ("Potatoes", "🥔", 32, "prod", 2), ("Carrots", "🥕", 52, "prod", 2), ("Spinach", "🥬", 40, "prod", 2),
        ("Broccoli", "🥦", 130, "prod", 2), ("Capsicum", "🫑", 80, "prod", 2), ("Cucumber", "🥒", 40, "prod", 2),
        ("Lemons", "🍋", 110, "prod", 2), ("Garlic", "🧄", 200, "prod", 2), ("Mushrooms", "🍄", 220, "prod", 2),
        ("Sweet Corn", "🌽", 60, "prod", 2),
    ],
    "dairy": [
        ("Full Cream Milk", "🥛", 68, "milk", 3), ("Toned Milk", "🥛", 58, "milk", 3),
        ("Fresh Curd", "🥣", 80, "tub", 2), ("Paneer", "🧀", 340, "tub", 2), ("Salted Butter", "🧈", 520, "tub", 2),
        ("Cheese Slices", "🧀", 480, "tub", 2), ("Farm Eggs", "🥚", 84, "eggs", 3),
        ("Greek Yogurt", "🥄", 300, "tub", 2), ("Buttermilk", "🥛", 25, "milk", 2), ("Fresh Cream", "🥛", 220, "tub", 2),
    ],
    "snacks": [
        ("Potato Chips", "🥔", 30, "pack", 3), ("Namkeen Mix", "🥨", 55, "pack", 2), ("Butter Popcorn", "🍿", 40, "pack", 2),
        ("Cream Biscuits", "🍪", 35, "pack", 2), ("Digestive Biscuits", "🍪", 60, "pack", 2),
        ("Dark Chocolate", "🍫", 150, "pack", 3), ("Instant Noodles", "🍜", 15, "pack", 2),
        ("Cola", "🥤", 40, "bottle", 2), ("Fruit Juice", "🧃", 90, "bottle", 2), ("Energy Drink", "⚡", 110, "bottle", 2),
        ("Green Tea Bags", "🍵", 180, "pack", 2), ("Instant Coffee", "☕", 260, "pack", 2),
        ("Protein Bars", "💪", 60, "pack", 2), ("Mixed Dry Fruits", "🥜", 450, "pack", 2),
        ("Festive Sweets Box", "🍬", 380, "pack", 2),
    ],
    "bakery": [
        ("White Bread", "🍞", 40, "pack", 3), ("Multigrain Bread", "🍞", 55, "pack", 2), ("Burger Buns", "🍔", 45, "pack", 2),
        ("Butter Croissant", "🥐", 70, "pack", 2), ("Chocolate Cake", "🎂", 450, "cake", 2),
        ("Blueberry Muffins", "🧁", 120, "pack", 2), ("Corn Flakes", "🥣", 190, "pack", 3),
        ("Muesli", "🥣", 280, "pack", 2), ("Peanut Butter", "🥜", 250, "jar", 3), ("Mixed Fruit Jam", "🍓", 120, "jar", 2),
        ("Wild Honey", "🍯", 260, "jar", 2), ("Pancake Mix", "🥞", 150, "pack", 2),
    ],
    "personal_care": [
        ("Shampoo", "🧴", 280, "bottle", 3), ("Conditioner", "🧴", 300, "bottle", 2), ("Body Wash", "🛁", 260, "bottle", 2),
        ("Bathing Soap", "🧼", 40, "pack", 3), ("Toothpaste", "🪥", 90, "pack", 3), ("Toothbrush", "🪥", 60, "pack", 2),
        ("Face Wash", "🧼", 220, "tube", 3), ("Moisturiser", "🧴", 320, "tube", 2), ("Sunscreen SPF 50", "☀️", 450, "tube", 2),
        ("Perfume", "🌸", 900, "perf", 3), ("Matte Lipstick", "💄", 450, "one", 3), ("Deodorant", "🧴", 220, "bottle", 2),
        ("Razor", "🪒", 150, "pack", 2), ("Hair Oil", "💆", 190, "bottle", 2),
    ],
    "home": [
        ("Detergent Powder", "🧺", 120, "kg", 3), ("Liquid Detergent", "🧴", 220, "litre", 2), ("Dishwash Gel", "🍽️", 110, "litre", 2),
        ("Floor Cleaner", "🧹", 130, "litre", 2), ("Toilet Cleaner", "🚽", 95, "litre", 2), ("Garbage Bags", "🗑️", 140, "pack", 2),
        ("Tissue Rolls", "🧻", 180, "pack", 2), ("Air Freshener", "🌺", 200, "bottle", 2), ("LED Bulb", "💡", 110, "bulb", 3),
        ("Extension Board", "🔌", 450, "one", 3), ("Mosquito Repellent", "🦟", 90, "pack", 2), ("Scrub Sponges", "🧽", 60, "pack", 2),
        ("Cotton Bed Sheet", "🛏️", 800, "bed", 3), ("Bath Towel Set", "🛁", 650, "set", 2), ("Door Mat", "🚪", 250, "one", 2),
    ],
    "baby": [
        ("Baby Diapers", "👶", 650, "dsize", 3), ("Baby Wipes", "🧻", 160, "pack", 2), ("Baby Lotion", "🧴", 240, "bottle", 2),
        ("Baby Shampoo", "🧴", 210, "bottle", 2), ("Infant Formula", "🍼", 650, "tin", 3), ("Baby Cereal", "🥣", 330, "pack", 2),
        ("Feeding Bottle", "🍼", 350, "one", 3), ("Baby Soap", "🧼", 90, "pack", 2), ("Kids Toothpaste", "🪥", 85, "pack", 2),
        ("Kids Puffs Snack", "🍘", 70, "pack", 2),
    ],
    "pet": [
        ("Dry Dog Food", "🐕", 520, "kg3", 3), ("Cat Food", "🐈", 480, "kg3", 3), ("Dog Treats", "🦴", 200, "pack", 2),
        ("Cat Litter", "🐈", 390, "kg3", 2), ("Pet Shampoo", "🧴", 280, "bottle", 2), ("Chew Toy", "🎾", 220, "one", 3),
        ("Fish Food", "🐟", 120, "pack", 2), ("Pet Bed", "🛏️", 1200, "bed", 2), ("Dog Leash", "🦮", 450, "one", 3),
        ("Bird Seed Mix", "🐦", 160, "pack", 2),
    ],
    "kitchen": [
        ("Non-stick Pan", "🍳", 899, "pan", 3), ("Pressure Cooker", "🥘", 1799, "cooker", 3), ("Chef Knife Set", "🔪", 799, "one", 3),
        ("Dinner Set", "🍽️", 2499, "set", 3), ("Steel Water Bottle", "🍶", 399, "bottle2", 3), ("Lunch Box", "🍱", 549, "one", 3),
        ("Mixer Grinder", "🌀", 3499, "model", 2), ("Electric Kettle", "♨️", 1299, "one", 3), ("Air Fryer", "🍟", 5999, "model", 2),
        ("Storage Containers", "🫙", 699, "set", 3), ("Ceramic Coffee Mugs", "☕", 449, "set", 3), ("Chopping Board", "🪵", 349, "one", 3),
        ("Induction Cooktop", "🔥", 2799, "one", 3), ("Pop-up Toaster", "🍞", 1799, "one", 3),
    ],
    "electronics": [
        ("Smartphone", "📱", 14999, "phone", 3), ("Laptop", "💻", 45999, "laptop", 3), ("Tablet", "📲", 18999, "phone", 2),
        ("Smart TV", "📺", 24999, "tv", 3), ("Bluetooth Speaker", "🔊", 2499, "model", 2), ("Wireless Headphones", "🎧", 3499, "model", 2),
        ("True Wireless Earbuds", "🎵", 1999, "model", 2), ("Smartwatch", "⌚", 4999, "model", 2), ("Power Bank", "🔋", 1299, "power", 3),
        ("Wi-Fi Router", "📶", 1799, "one", 3), ("Webcam", "📷", 2499, "one", 2), ("Monitor", "🖥️", 11999, "mon", 3),
        ("Mechanical Keyboard", "⌨️", 2999, "one", 3), ("Wireless Mouse", "🖱️", 899, "one", 3), ("Inkjet Printer", "🖨️", 8999, "one", 2),
        ("Action Camera", "🎥", 7999, "one", 2), ("Fitness Band", "⌚", 2499, "model", 2),
    ],
    "mobile": [
        ("Phone Case", "📱", 399, "case", 3), ("Tempered Glass", "🛡️", 249, "one", 3), ("Fast Charger", "🔌", 899, "charger", 3),
        ("USB-C Cable", "🔗", 349, "cable", 3), ("Wireless Charger", "⚡", 1499, "one", 3), ("Car Phone Mount", "🚗", 549, "one", 3),
        ("Memory Card", "💾", 799, "card", 3), ("Selfie Stick", "🤳", 599, "one", 2), ("Phone Stand", "📐", 399, "one", 2),
        ("Wired Earphones", "🎧", 699, "one", 3), ("Pop Grip", "⭕", 199, "one", 2),
    ],
    "games": [
        ("Gaming Console", "🎮", 39999, "console", 2), ("Wireless Controller", "🕹️", 4999, "one", 3),
        ("Racing Game", "🏎️", 2999, "platform", 3), ("Adventure Game", "🗺️", 3499, "platform", 3),
        ("Sports Game", "⚽", 2799, "platform", 3), ("Strategy Game", "♟️", 2499, "platform", 2),
        ("Board Game", "🎲", 999, "board", 3), ("Jigsaw Puzzle", "🧩", 499, "puz", 3), ("Building Blocks", "🧱", 1499, "blocks", 3),
        ("RC Car", "🚙", 1799, "one", 3), ("Soft Toy", "🧸", 599, "toy", 3), ("Playing Cards", "🃏", 149, "one", 2),
        ("Art & Craft Kit", "🎨", 699, "one", 3), ("Gaming Headset", "🎧", 2999, "one", 3), ("Action Figure", "🦸", 699, "one", 3),
    ],
    "sports": [
        ("Yoga Mat", "🧘", 799, "mat", 3), ("Dumbbell Set", "🏋️", 1999, "weights", 3), ("Whey Protein", "🥤", 2499, "protein", 3),
        ("Resistance Bands", "🎗️", 499, "one", 3), ("Skipping Rope", "🪢", 249, "one", 3), ("Cricket Bat", "🏏", 1999, "one", 3),
        ("Football", "⚽", 899, "one", 3), ("Badminton Racket", "🏸", 1299, "one", 3), ("Running Shoes", "👟", 2999, "fit", 3),
        ("Gym Bag", "🎒", 899, "one", 3), ("Sports Water Bottle", "💧", 449, "one", 3), ("Shaker Bottle", "🥤", 299, "one", 2),
        ("Cycling Helmet", "⛑️", 1299, "one", 3), ("Multivitamin Tablets", "💊", 699, "tabs", 3), ("Creatine", "💪", 1299, "protein", 2),
    ],
    "fashion": [
        ("Cotton T-Shirt", "👕", 599, "fit", 3), ("Denim Jeans", "👖", 1599, "fit", 3), ("Cotton Kurta", "👘", 1199, "fit", 3),
        ("Silk Saree", "🥻", 2499, "fit", 3), ("Summer Dress", "👗", 1999, "fit", 3), ("Sneakers", "👟", 2799, "fit", 3),
        ("Sandals", "🩴", 899, "fit", 2), ("Winter Jacket", "🧥", 3299, "fit", 3), ("Cotton Socks", "🧦", 249, "socks", 2),
        ("Analog Wrist Watch", "⌚", 2499, "fit", 3), ("Sunglasses", "🕶️", 1299, "fit", 2), ("Handbag", "👜", 1999, "fit", 3),
        ("Laptop Backpack", "🎒", 1499, "fit", 2), ("Baseball Cap", "🧢", 399, "fit", 2), ("Formal Shirt", "👔", 1299, "fit", 3),
        ("Woollen Scarf", "🧣", 699, "fit", 2), ("Jewellery Set", "💍", 1499, "fit", 3),
    ],
    "books": [
        ("Ruled Notebooks", "📓", 90, "nb", 3), ("Gel Pens", "🖊️", 120, "pack", 3), ("Highlighters", "🖍️", 150, "one", 2),
        ("Geometry Box", "📐", 180, "one", 2), ("Mystery Novel", "📖", 349, "book", 2), ("Self-Help Book", "📘", 399, "book", 2),
        ("Science Fiction Novel", "📗", 379, "book", 2), ("Children's Story Book", "📚", 249, "book", 3),
        ("Competitive Exam Guide", "📝", 699, "book", 2), ("Coloured Pencils", "🖍️", 160, "pack", 3), ("Sticky Notes", "🗒️", 99, "one", 2),
        ("Desk Organiser", "🗃️", 499, "one", 2), ("Daily Planner", "📅", 299, "one", 3), ("Scientific Calculator", "🧮", 899, "one", 2),
        ("Sketchbook", "🎨", 249, "one", 2), ("Cookbook", "🍳", 549, "book", 2), ("Biography", "📙", 449, "book", 2),
    ],
}
POOL_FOR = {k: (k if k in POOLS else None) for k in CAT_KEYS}
POOL_FOR.update({"personal_care": "beauty"})

# Durable categories hold one-off purchases; these specific families are consumable.
CONSUMABLE_FAMILIES = {"Whey Protein", "Multivitamin Tablets", "Creatine", "Gel Pens", "Ruled Notebooks", "Coloured Pencils"}

# Margin (cost as a share of price) by category
COST_RATIO = {
    "staples": .90, "produce": .82, "dairy": .88, "snacks": .78, "bakery": .72, "personal_care": .58, "home": .66,
    "baby": .80, "pet": .74, "kitchen": .68, "electronics": .87, "mobile": .55, "games": .84, "sports": .66,
    "fashion": .55, "books": .72,
}
STOCK_RANGE = {
    "staples": (60, 400), "produce": (30, 220), "dairy": (30, 240), "snacks": (50, 420), "bakery": (20, 160),
    "personal_care": (30, 260), "home": (30, 260), "baby": (20, 160), "pet": (15, 120), "kitchen": (6, 70),
    "electronics": (3, 40), "mobile": (15, 160), "games": (5, 60), "sports": (8, 80), "fashion": (10, 100), "books": (15, 120),
}


def _nice(p):
    if p < 50:
        return max(1, int(round(p)))
    if p < 100:
        return int(round(p / 5.0) * 5)
    if p < 10000:
        return int(round(p / 10.0) * 10 - 1)
    return int(round(p / 100.0) * 100 - 1)


def build_catalog(rng):
    """Return a list of product dicts (without ids; the DB assigns them)."""
    products = []
    n = 0
    for cat in CAT_KEYS:
        pool = POOLS[POOL_FOR[cat]]
        for name, emoji, base, size_key, nb in FAMILIES[cat]:
            consumable = int(CAT_META[cat]["cycle"] is not None or name in CONSUMABLE_FAMILIES)
            for brand, tier in pool[:nb] if nb < 3 else pool:
                for label, mult in SIZES[size_key]:
                    n += 1
                    price = _nice(base * mult * TIER_FACTOR[tier] * rng.uniform(0.96, 1.04))
                    promo = rng.random() < 0.27
                    mrp = _nice(price / (1 - rng.uniform(0.08, 0.30))) if promo else price
                    if mrp <= price:
                        mrp = price
                    lo, hi = STOCK_RANGE[cat]
                    stock = int(rng.integers(lo, hi))
                    r = rng.random()
                    if r < 0.025:
                        stock = 0
                    elif r < 0.07:
                        stock = int(rng.integers(1, 6))
                    products.append({
                        "sku": "SKU%05d" % n, "name": "%s %s" % (brand, name), "emoji": emoji, "category": cat,
                        "family": name, "brand": brand, "brand_tier": tier, "unit": label,
                        "price": float(price), "mrp": float(mrp),
                        "cost": round(price * COST_RATIO[cat] * rng.uniform(0.95, 1.05), 2),
                        "stock": stock, "reorder_level": max(5, int(hi * 0.12)),
                        "consumable": consumable, "rating": round(float(rng.uniform(3.6, 4.9)), 1),
                        "pop": float(rng.lognormal(0, 0.8)) * (1.4 if tier != "premium" else 0.8),
                    })
    return products


def log_round(x):
    return math.log(max(x, 1.0))
