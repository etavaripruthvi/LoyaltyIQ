"""Ten customer personas, each with a distinct, measurable shopping behaviour.

These drive the synthetic order history. The persona label is stored on the customer row
as hidden ground truth, so we can later check whether the AI *recovers* these behaviours
from raw orders alone (it never sees the label)."""

# Seasonality: month number -> multiplier on order rate (default 1.0)
FESTIVE = {10: 6.0, 11: 7.0, 12: 1.4, 4: 1.8}
TECH_BURSTS = {2: 3.5, 9: 4.0, 11: 3.0}
SUMMER_STYLE = {3: 1.4, 4: 1.5, 10: 1.8, 11: 1.8, 12: 1.3}

PERSONAS = {
    "deal_hunter": dict(
        label="Deal-hunter", name="Divya Rao", showcase_user=1,
        blurb="Buys mostly discounted staples, snacks and household items in frequent small baskets.",
        cats=dict(staples=.22, snacks=.15, personal_care=.15, home=.15, dairy=.08, produce=.08, bakery=.05,
                  kitchen=.04, baby=.02, pet=.02, books=.02, fashion=.02),
        tier_pref=(.60, .33, .07), discount_sens=.88, budget=.75, orders_per_month=2.8, basket=4.0,
        repeat=.35, qty_extra=.25, redeem_prob=.6, return_rate=.02, season={}, weight=18),
    "premium": dict(
        label="Premium shopper", name="Pranav Mehta", showcase_user=2,
        blurb="High-value baskets of premium brands, rarely chases discounts.",
        cats=dict(electronics=.20, fashion=.20, personal_care=.15, kitchen=.12, snacks=.08, produce=.06,
                  sports=.06, home=.05, bakery=.04, games=.04),
        tier_pref=(.04, .30, .66), discount_sens=.06, budget=1.9, orders_per_month=2.0, basket=3.2,
        repeat=.15, qty_extra=.05, redeem_prob=.05, return_rate=.04, season={}, weight=8),
    "techie": dict(
        label="Tech enthusiast", name="Tarun Iyer", showcase_user=3,
        blurb="Electronics, accessories and games; buys in bursts around launch seasons.",
        cats=dict(electronics=.30, mobile=.30, games=.20, snacks=.05, books=.03, sports=.03, kitchen=.03, home=.02, fashion=.02),
        tier_pref=(.15, .45, .40), discount_sens=.30, budget=1.2, orders_per_month=0.9, basket=3.0,
        repeat=.08, qty_extra=.03, redeem_prob=.2, return_rate=.05, season=TECH_BURSTS, weight=10),
    "parent": dict(
        label="Busy parent", name="Meera Nair", showcase_user=4,
        blurb="Weekly restocking of groceries, dairy, baby and home essentials.",
        cats=dict(staples=.20, produce=.18, dairy=.15, baby=.18, home=.10, snacks=.07, bakery=.06, personal_care=.04, pet=.02),
        tier_pref=(.20, .60, .20), discount_sens=.45, budget=1.0, orders_per_month=4.2, basket=7.0,
        repeat=.62, qty_extra=.5, redeem_prob=.3, return_rate=.01, season={}, weight=15),
    "fitness": dict(
        label="Fitness fanatic", name="Farhan Qureshi", showcase_user=5,
        blurb="Sports gear, supplements and healthy food on a steady monthly rhythm.",
        cats=dict(sports=.32, produce=.15, dairy=.12, snacks=.10, staples=.09, fashion=.08, personal_care=.06, bakery=.05, books=.03),
        tier_pref=(.15, .55, .30), discount_sens=.30, budget=1.2, orders_per_month=1.6, basket=5.0,
        repeat=.55, qty_extra=.2, redeem_prob=.25, return_rate=.03, season={}, weight=10),
    "trendy": dict(
        label="Trend follower", name="Tanya Kapoor", showcase_user=6,
        blurb="Fashion and beauty, impulsive and seasonal, with a high return rate.",
        cats=dict(fashion=.36, personal_care=.30, mobile=.08, snacks=.06, electronics=.03, home=.05, books=.04, bakery=.03, kitchen=.03),
        tier_pref=(.15, .45, .40), discount_sens=.50, budget=1.1, orders_per_month=1.8, basket=3.2,
        repeat=.12, qty_extra=.05, redeem_prob=.3, return_rate=.24, season=SUMMER_STYLE, weight=10),
    "festive": dict(
        label="Festive gifter", name="Gopal Sharma", showcase_user=7,
        blurb="Big gift baskets almost only around Diwali and wedding season.",
        cats=dict(snacks=.25, fashion=.20, home=.15, kitchen=.15, electronics=.10, games=.05, personal_care=.05, staples=.05),
        tier_pref=(.10, .50, .40), discount_sens=.35, budget=1.25, orders_per_month=0.30, basket=6.0,
        repeat=.10, qty_extra=.15, redeem_prob=.2, return_rate=.03, season=FESTIVE, weight=8),
    "student": dict(
        label="Student", name="Sana Fernandes", showcase_user=8,
        blurb="Small low-budget baskets of books, snacks and accessories; loves redeeming points.",
        cats=dict(books=.36, snacks=.24, mobile=.12, games=.04, personal_care=.07, fashion=.05, electronics=0.0, staples=.07, sports=.05),
        tier_pref=(.60, .35, .05), discount_sens=.72, budget=.45, orders_per_month=1.4, basket=2.2,
        repeat=.2, qty_extra=.1, redeem_prob=.85, return_rate=.02, season={}, weight=10),
    "lapsed": dict(
        label="Lapsed regular", name="Lakshmi Venkat", showcase_user=9,
        blurb="Used to be a top regular, then went quiet about five months ago.",
        cats=dict(home=.20, produce=.15, fashion=.20, dairy=.10, staples=.15, kitchen=.10, personal_care=.10),
        tier_pref=(.15, .55, .30), discount_sens=.40, budget=1.3, orders_per_month=3.2, basket=5.0,
        repeat=.5, qty_extra=.3, redeem_prob=.2, return_rate=.03, season={}, weight=6, lapse_days=(110, 210)),
    "newbie": dict(
        label="New customer", name="Nikhil Joshi", showcase_user=10,
        blurb="Signed up two weeks ago with a single order: tests the cold-start path.",
        cats=dict(games=.30, electronics=.25, snacks=.20, mobile=.15, books=.10),
        tier_pref=(.25, .50, .25), discount_sens=.4, budget=1.0, orders_per_month=1, basket=3.0,
        repeat=0, qty_extra=0, redeem_prob=0, return_rate=0, season={}, weight=5, join_days=(5, 24)),
}
SHOWCASE_ORDER = sorted(PERSONAS, key=lambda k: PERSONAS[k]["showcase_user"])

FIRST_NAMES = ["Aarav", "Aditi", "Aisha", "Ajay", "Akash", "Ananya", "Anil", "Anjali", "Arjun", "Bhavna", "Chetan", "Deepa",
               "Dev", "Esha", "Faisal", "Gauri", "Harish", "Isha", "Jatin", "Kavya", "Kiran", "Lata", "Manish", "Mohit",
               "Nandini", "Neha", "Omkar", "Pooja", "Priya", "Rahul", "Rajesh", "Riya", "Rohan", "Sachin", "Sakshi",
               "Sanjay", "Shreya", "Siddharth", "Sneha", "Suresh", "Tanvi", "Uday", "Varun", "Vikram", "Zoya", "Imran",
               "Karthik", "Lavanya", "Meenal", "Naveen"]
LAST_NAMES = ["Agarwal", "Bhat", "Chopra", "Desai", "Gupta", "Hegde", "Jain", "Khan", "Kulkarni", "Menon", "Naidu", "Patel",
              "Reddy", "Saxena", "Singh", "Thomas", "Verma", "Pillai", "Banerjee", "Das", "Mishra", "Shetty", "Bose", "Yadav"]
CITIES = ["Mumbai", "Delhi", "Bengaluru", "Chennai", "Hyderabad", "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Kochi"]
