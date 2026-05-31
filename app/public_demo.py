"""Synthetic public demo data used when the private evaluation package is absent."""

PUBLIC_POLICY_SECTIONS = [
    ("TEP-001", "Synthetic Expense Overview", "1", "Business purpose", "1. Business purpose\nEvery reimbursable expense must have a documented business purpose."),
    ("TEP-007", "Synthetic Receipt Requirements", "2", "Documentation", "2. Documentation\nA valid receipt must show merchant, date, total amount, and payment method."),
    ("TEP-002", "Synthetic Meals Policy", "2.2", "Meal caps", "2.2 Meal caps\nExpenses above these caps are not reimbursable: breakfast $25, lunch $35, and dinner $75 per traveler, inclusive of tax and tip."),
    ("TEP-002", "Synthetic Meals Policy", "3", "Tips", "3. Tips\nTips above 20% of the pre-tax meal amount are personal and not reimbursable."),
    ("TEP-003", "Synthetic Alcohol Policy", "3.1", "Solo travel", "3.1 Solo travel\nAny alcoholic beverage purchased while traveling on business without external clients present is not reimbursable."),
    ("TEP-004", "Synthetic Lodging Policy", "2.1", "Booking tool", "2.1 Booking tool\nBookings outside the tool require manager approval and a written justification."),
    ("TEP-004", "Synthetic Lodging Policy", "3", "City rate caps", "3. City rate caps\nMaximum reimbursable nightly rate: Tier 1 cities $350, Tier 2 cities $250, and other domestic cities $175."),
    ("TEP-005", "Synthetic Air Travel Policy", "2.2", "Premium economy", "2.2 Premium economy\nPremium economy is permitted for a scheduled duration of 6 hours or more."),
    ("TEP-006", "Synthetic Ground Transportation Policy", "2.1", "Rideshare", "2.1 Rideshare\nStandard rideshare services such as UberX and Lyft Standard are reimbursable for business airport transfers."),
    ("TEP-006", "Synthetic Ground Transportation Policy", "2.2", "Premium rideshare", "2.2 Premium rideshare\nPremium categories require a written explanation that no standard option was available."),
    ("TEP-014", "Synthetic Conference Policy", "5.1", "Included meals", "5.1 Included meals\nWhen conference registration includes a meal, no separate reimbursement is available for that meal."),
]

PUBLIC_EMPLOYEES = [
    {"employee_id": "DEMO-1001", "name": "Avery Morgan", "grade": 5, "title": "Operations Manager", "department": "Operations", "manager_id": "DEMO-9001", "home_base": "Irvine, CA"},
    {"employee_id": "DEMO-1002", "name": "Jordan Lee", "grade": 6, "title": "Client Services Manager", "department": "Client Services", "manager_id": "DEMO-9001", "home_base": "Irvine, CA"},
]

PUBLIC_SUBMISSIONS = [
    {
        "source_label": "public_demo_clean",
        "employee_id": "DEMO-1001",
        "trip_purpose": "Synthetic client operations review in Denver",
        "trip_dates": "2025-07-10 to 2025-07-11",
        "receipts": [("demo_dinner.txt", "SAMPLE BISTRO\n10 Jul 2025  7:10 PM\n  1  Pasta $24.00\n  1  Iced Tea $4.00\nSubtotal $28.00\nTax $2.00\nGRAND TOTAL $30.00\nVisa ****1234")],
    },
    {
        "source_label": "public_demo_flagged",
        "employee_id": "DEMO-1002",
        "trip_purpose": "Synthetic client services trip in Austin",
        "trip_dates": "2025-07-10 to 2025-07-11",
        "receipts": [("demo_solo_alcohol.txt", "SAMPLE GRILL\n10 Jul 2025  8:10 PM\n  1  Burger $22.00\n  1  Beer $8.00\nSubtotal $30.00\nTax $2.00\nGRAND TOTAL $32.00\nVisa ****1234\nNOTE: Solo diner. No external attendees.")],
    },
]
