#!/usr/bin/env python3
"""
Add high-calorie nutrient-dense meals for user.
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("Error: Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    sys.exit(1)

client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Get user ID from prefs (first user found, or specify)
def get_user_id():
    result = client.table("foodos2_preference_profiles").select("user_id").limit(1).execute()
    if result.data:
        return result.data[0]["user_id"]
    return None

# High-calorie nutrient-dense meals
MEALS = [
    {
        "name": "Beef & Sweet Potato Power Bowl",
        "calories_per_100g": 145,
        "protein_g_per_100g": 12,
        "carbs_g_per_100g": 10,
        "fat_g_per_100g": 7,
        "base_calories": 850,
        "notes": "Ground beef, roasted sweet potato, avocado, black beans, cheese. High in iron, B12, potassium.",
    },
    {
        "name": "Salmon Quinoa Bowl",
        "calories_per_100g": 155,
        "protein_g_per_100g": 14,
        "carbs_g_per_100g": 12,
        "fat_g_per_100g": 6,
        "base_calories": 780,
        "notes": "Baked salmon, quinoa, roasted broccoli, olive oil drizzle. High omega-3, complete protein.",
    },
    {
        "name": "Chicken Thigh Peanut Stir Fry",
        "calories_per_100g": 165,
        "protein_g_per_100g": 13,
        "carbs_g_per_100g": 14,
        "fat_g_per_100g": 8,
        "base_calories": 820,
        "notes": "Crispy chicken thighs, brown rice, vegetables in peanut sauce. High protein and healthy fats.",
    },
    {
        "name": "Greek Lamb Meatball Plate",
        "calories_per_100g": 175,
        "protein_g_per_100g": 14,
        "carbs_g_per_100g": 15,
        "fat_g_per_100g": 9,
        "base_calories": 800,
        "notes": "Spiced lamb meatballs, hummus, feta, pita, cucumber salad. Mediterranean nutrients.",
    },
    {
        "name": "Loaded Turkey Burrito Bowl",
        "calories_per_100g": 140,
        "protein_g_per_100g": 11,
        "carbs_g_per_100g": 14,
        "fat_g_per_100g": 5,
        "base_calories": 850,
        "notes": "Ground turkey, black beans, rice, guacamole, cheese, salsa. High fiber and protein.",
    },
    {
        "name": "Steak & Egg Breakfast Hash",
        "calories_per_100g": 160,
        "protein_g_per_100g": 14,
        "carbs_g_per_100g": 8,
        "fat_g_per_100g": 9,
        "base_calories": 750,
        "notes": "Sirloin steak, fried eggs, crispy potatoes, peppers. Breakfast of champions.",
    },
    {
        "name": "Shrimp & Grits Southern Style",
        "calories_per_100g": 150,
        "protein_g_per_100g": 12,
        "carbs_g_per_100g": 16,
        "fat_g_per_100g": 5,
        "base_calories": 720,
        "notes": "Garlic butter shrimp over creamy cheddar grits with bacon. High protein, selenium.",
    },
    {
        "name": "Thai Pork Larb Bowl",
        "calories_per_100g": 145,
        "protein_g_per_100g": 13,
        "carbs_g_per_100g": 12,
        "fat_g_per_100g": 6,
        "base_calories": 700,
        "notes": "Spicy ground pork with herbs, jasmine rice, fresh vegetables. Bright and nutritious.",
    },
    {
        "name": "Mediterranean Chicken & Orzo",
        "calories_per_100g": 155,
        "protein_g_per_100g": 13,
        "carbs_g_per_100g": 15,
        "fat_g_per_100g": 6,
        "base_calories": 780,
        "notes": "Herb roasted chicken, orzo pasta, sun-dried tomatoes, olives, feta.",
    },
    {
        "name": "Carnitas Rice Bowl",
        "calories_per_100g": 170,
        "protein_g_per_100g": 14,
        "carbs_g_per_100g": 13,
        "fat_g_per_100g": 8,
        "base_calories": 830,
        "notes": "Slow-cooked pork carnitas, cilantro lime rice, pinto beans, pickled onions.",
    },
    {
        "name": "Tuscan White Bean & Sausage Soup",
        "calories_per_100g": 125,
        "protein_g_per_100g": 9,
        "carbs_g_per_100g": 10,
        "fat_g_per_100g": 6,
        "base_calories": 650,
        "notes": "Italian sausage, white beans, kale, parmesan. Hearty and fiber-rich.",
    },
    {
        "name": "Teriyaki Salmon Rice Bowl",
        "calories_per_100g": 160,
        "protein_g_per_100g": 14,
        "carbs_g_per_100g": 14,
        "fat_g_per_100g": 6,
        "base_calories": 750,
        "notes": "Glazed salmon, sushi rice, edamame, pickled ginger, sesame. Omega-3 rich.",
    },
    {
        "name": "BBQ Brisket Mac & Cheese",
        "calories_per_100g": 185,
        "protein_g_per_100g": 12,
        "carbs_g_per_100g": 16,
        "fat_g_per_100g": 10,
        "base_calories": 900,
        "notes": "Smoked brisket over creamy mac and cheese with pickles. Ultimate comfort food.",
    },
    {
        "name": "Moroccan Chicken & Couscous",
        "calories_per_100g": 145,
        "protein_g_per_100g": 12,
        "carbs_g_per_100g": 15,
        "fat_g_per_100g": 5,
        "base_calories": 720,
        "notes": "Spiced chicken thighs, pearl couscous, chickpeas, dried apricots, almonds.",
    },
    {
        "name": "Korean Beef Bibimbap",
        "calories_per_100g": 150,
        "protein_g_per_100g": 11,
        "carbs_g_per_100g": 16,
        "fat_g_per_100g": 5,
        "base_calories": 780,
        "notes": "Bulgogi beef, rice, vegetables, fried egg, gochujang. Complete balanced meal.",
    },
]


def main():
    user_id = get_user_id()
    if not user_id:
        print("No user found in preference_profiles")
        sys.exit(1)

    print(f"Adding meals for user: {user_id}")

    for meal in MEALS:
        data = {
            "user_id": user_id,
            "kind": "meal",
            "name": meal["name"],
            "calories_per_100g": meal["calories_per_100g"],
            "protein_g_per_100g": meal["protein_g_per_100g"],
            "carbs_g_per_100g": meal["carbs_g_per_100g"],
            "fat_g_per_100g": meal["fat_g_per_100g"],
            "base_calories": meal["base_calories"],
            "scaling_mode": "by_calories",
            "is_premade": False,
            "is_public": False,
            "notes": meal["notes"],
        }

        try:
            result = client.table("foodos2_food_items").insert(data).execute()
            print(f"  ✓ Added: {meal['name']}")
        except Exception as e:
            print(f"  ✗ Failed: {meal['name']} - {e}")

    print(f"\nDone! Added {len(MEALS)} meals.")


if __name__ == "__main__":
    main()
