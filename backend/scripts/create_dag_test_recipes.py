#!/usr/bin/env python3
"""
Create DAG test recipes: Gyros meal with Tzatziki and Pita as sub-recipes.

This script demonstrates and tests the DAG recipe system where:
- Tzatziki Sauce is a standalone recipe (meal)
- Pita Bread is a standalone recipe (meal)
- Greek Gyros Plate is a parent recipe that includes Tzatziki and Pita as components

Run: python -m scripts.create_dag_test_recipes
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.supabase import get_supabase_client, TABLES
from app.services.recipes import flatten_recipe, clear_recipe_caches

# Default user ID (Xander)
USER_ID = "5fc549ee-ce69-4539-b3d7-73b8637c21bc"


def get_or_create_ingredient(client, name: str, nutrition: dict) -> str:
    """Get existing ingredient or create a new one."""
    # Check if exists
    result = client.table(TABLES["items"]).select("id").eq(
        "user_id", USER_ID
    ).ilike("name", name).limit(1).execute()

    if result.data:
        print(f"  Found existing: {name} ({result.data[0]['id'][:8]}...)")
        return result.data[0]["id"]

    # Create new
    item = {
        "user_id": USER_ID,
        "name": name,
        "kind": "ingredient",
        "calories_per_100g": nutrition.get("calories", 0),
        "protein_g_per_100g": nutrition.get("protein", 0),
        "carbs_g_per_100g": nutrition.get("carbs", 0),
        "fat_g_per_100g": nutrition.get("fat", 0),
    }
    result = client.table(TABLES["items"]).insert(item).execute()
    item_id = result.data[0]["id"]
    print(f"  Created: {name} ({item_id[:8]}...)")
    return item_id


def create_recipe(client, name: str, kind: str, description: str, nutrition: dict) -> str:
    """Create a recipe food item."""
    # Check if exists
    result = client.table(TABLES["items"]).select("id").eq(
        "user_id", USER_ID
    ).ilike("name", name).limit(1).execute()

    if result.data:
        print(f"  Found existing recipe: {name} ({result.data[0]['id'][:8]}...)")
        return result.data[0]["id"]

    item = {
        "user_id": USER_ID,
        "name": name,
        "kind": kind,
        "notes": description,
        "calories_per_100g": nutrition.get("calories", 0),
        "protein_g_per_100g": nutrition.get("protein", 0),
        "carbs_g_per_100g": nutrition.get("carbs", 0),
        "fat_g_per_100g": nutrition.get("fat", 0),
    }
    result = client.table(TABLES["items"]).insert(item).execute()
    item_id = result.data[0]["id"]
    print(f"  Created recipe: {name} ({item_id[:8]}...)")
    return item_id


def create_recipe_edge(client, parent_id: str, child_id: str, amount_g: float, sort_order: int = 0):
    """Create a recipe edge (parent -> child relationship)."""
    # Check if edge already exists
    result = client.table(TABLES["recipe_edges"]).select("id").eq(
        "parent_food_item_id", parent_id
    ).eq("child_food_item_id", child_id).limit(1).execute()

    if result.data:
        print(f"    Edge already exists")
        return result.data[0]["id"]

    edge = {
        "user_id": USER_ID,
        "parent_food_item_id": parent_id,
        "child_food_item_id": child_id,
        "amount_g": amount_g,
        "storage_mode": "absolute",
        "sort_order": sort_order,
    }
    result = client.table(TABLES["recipe_edges"]).insert(edge).execute()
    edge_id = result.data[0]["id"]
    print(f"    Created edge: {amount_g}g (sort: {sort_order})")
    return edge_id


def create_recipe_node(client, food_item_id: str, prep_time: int, cook_time: int,
                       prep_steps: list[str], base_serving_g: float):
    """Create recipe metadata (timing, steps)."""
    # Check if exists
    result = client.table(TABLES["recipe_nodes"]).select("food_item_id").eq(
        "food_item_id", food_item_id
    ).limit(1).execute()

    if result.data:
        print(f"    Recipe node already exists")
        return

    node = {
        "user_id": USER_ID,
        "food_item_id": food_item_id,
        "prep_time_minutes": prep_time,
        "cook_time_minutes": cook_time,
        "prep_steps": prep_steps,
        "base_serving_g": base_serving_g,
    }
    client.table(TABLES["recipe_nodes"]).insert(node).execute()
    print(f"    Created recipe node (prep: {prep_time}m, cook: {cook_time}m)")


async def main():
    print("=" * 60)
    print("Creating DAG Test Recipes: Greek Gyros with Sub-Recipes")
    print("=" * 60)

    client = get_supabase_client()

    # =========================================================================
    # Step 1: Create/get ingredients
    # =========================================================================
    print("\n1. Creating ingredients...")

    # Tzatziki ingredients
    yogurt_id = get_or_create_ingredient(client, "Greek Yogurt (Full Fat)", {
        "calories": 120, "protein": 10, "carbs": 4, "fat": 7
    })
    cucumber_id = get_or_create_ingredient(client, "Cucumber", {
        "calories": 15, "protein": 0.7, "carbs": 3.6, "fat": 0.1
    })
    garlic_id = get_or_create_ingredient(client, "Garlic", {
        "calories": 149, "protein": 6.4, "carbs": 33, "fat": 0.5
    })
    dill_id = get_or_create_ingredient(client, "Fresh Dill", {
        "calories": 43, "protein": 3.5, "carbs": 7, "fat": 1.1
    })
    lemon_juice_id = get_or_create_ingredient(client, "Lemon Juice", {
        "calories": 22, "protein": 0.4, "carbs": 7, "fat": 0.2
    })
    olive_oil_id = get_or_create_ingredient(client, "Olive Oil", {
        "calories": 884, "protein": 0, "carbs": 0, "fat": 100
    })
    salt_id = get_or_create_ingredient(client, "Salt", {
        "calories": 0, "protein": 0, "carbs": 0, "fat": 0
    })

    # Pita ingredients
    flour_id = get_or_create_ingredient(client, "All-Purpose Flour", {
        "calories": 364, "protein": 10, "carbs": 76, "fat": 1
    })
    yeast_id = get_or_create_ingredient(client, "Active Dry Yeast", {
        "calories": 325, "protein": 40, "carbs": 42, "fat": 7
    })
    water_id = get_or_create_ingredient(client, "Water", {
        "calories": 0, "protein": 0, "carbs": 0, "fat": 0
    })
    sugar_id = get_or_create_ingredient(client, "Sugar", {
        "calories": 387, "protein": 0, "carbs": 100, "fat": 0
    })

    # Gyros meat ingredients
    lamb_id = get_or_create_ingredient(client, "Ground Lamb", {
        "calories": 283, "protein": 17, "carbs": 0, "fat": 23
    })
    beef_id = get_or_create_ingredient(client, "Ground Beef (80/20)", {
        "calories": 254, "protein": 17, "carbs": 0, "fat": 20
    })
    onion_id = get_or_create_ingredient(client, "Onion", {
        "calories": 40, "protein": 1.1, "carbs": 9.3, "fat": 0.1
    })
    oregano_id = get_or_create_ingredient(client, "Dried Oregano", {
        "calories": 265, "protein": 9, "carbs": 69, "fat": 4
    })
    cumin_id = get_or_create_ingredient(client, "Ground Cumin", {
        "calories": 375, "protein": 18, "carbs": 44, "fat": 22
    })
    paprika_id = get_or_create_ingredient(client, "Paprika", {
        "calories": 282, "protein": 14, "carbs": 54, "fat": 13
    })

    # Toppings
    tomato_id = get_or_create_ingredient(client, "Tomato", {
        "calories": 18, "protein": 0.9, "carbs": 3.9, "fat": 0.2
    })
    red_onion_id = get_or_create_ingredient(client, "Red Onion", {
        "calories": 40, "protein": 1.1, "carbs": 9.3, "fat": 0.1
    })

    # =========================================================================
    # Step 2: Create Tzatziki Sauce recipe
    # =========================================================================
    print("\n2. Creating Tzatziki Sauce recipe (sub-recipe)...")

    tzatziki_id = create_recipe(client, "Homemade Tzatziki Sauce", "meal",
        "Cool, creamy Greek cucumber-yogurt sauce. Perfect for gyros, kebabs, or as a dip.",
        {"calories": 80, "protein": 5, "carbs": 4, "fat": 5, "serving_g": 150}
    )

    print("  Adding ingredients to Tzatziki:")
    create_recipe_edge(client, tzatziki_id, yogurt_id, 200, 1)  # 200g yogurt
    create_recipe_edge(client, tzatziki_id, cucumber_id, 100, 2)  # 100g cucumber
    create_recipe_edge(client, tzatziki_id, garlic_id, 10, 3)  # 2 cloves
    create_recipe_edge(client, tzatziki_id, dill_id, 10, 4)  # fresh dill
    create_recipe_edge(client, tzatziki_id, lemon_juice_id, 15, 5)  # 1 tbsp
    create_recipe_edge(client, tzatziki_id, olive_oil_id, 15, 6)  # 1 tbsp
    create_recipe_edge(client, tzatziki_id, salt_id, 2, 7)  # pinch

    create_recipe_node(client, tzatziki_id, 15, 0, [
        "Grate cucumber and squeeze out excess moisture with paper towels",
        "Mince garlic and chop fresh dill",
        "In a bowl, combine Greek yogurt, grated cucumber, garlic, and dill",
        "Add olive oil and lemon juice, mix well",
        "Season with salt to taste",
        "Refrigerate for at least 30 minutes to let flavors meld"
    ], 350)

    # =========================================================================
    # Step 3: Create Pita Bread recipe
    # =========================================================================
    print("\n3. Creating Homemade Pita Bread recipe (sub-recipe)...")

    pita_id = create_recipe(client, "Homemade Pita Bread", "meal",
        "Soft, fluffy homemade pita bread with pockets. Makes 6 pitas.",
        {"calories": 165, "protein": 5.5, "carbs": 33, "fat": 1.5, "serving_g": 60}
    )

    print("  Adding ingredients to Pita:")
    create_recipe_edge(client, pita_id, flour_id, 300, 1)  # 2.5 cups
    create_recipe_edge(client, pita_id, yeast_id, 7, 2)  # 1 packet
    create_recipe_edge(client, pita_id, water_id, 200, 3)  # warm water
    create_recipe_edge(client, pita_id, sugar_id, 5, 4)  # 1 tsp
    create_recipe_edge(client, pita_id, salt_id, 5, 5)  # 1 tsp
    create_recipe_edge(client, pita_id, olive_oil_id, 15, 6)  # 1 tbsp

    create_recipe_node(client, pita_id, 20, 15, [
        "Dissolve sugar in warm water, add yeast, let bloom for 5 minutes",
        "Mix flour and salt in a large bowl",
        "Add yeast mixture and olive oil, knead for 8-10 minutes until smooth",
        "Cover and let rise for 1 hour until doubled",
        "Divide into 6 balls, roll each into 6-inch circles",
        "Preheat oven to 475°F (245°C) with baking stone",
        "Bake pitas 3-4 minutes until puffed and lightly golden"
    ], 530)  # Total dough weight

    # =========================================================================
    # Step 4: Create Gyros Meat recipe (also a sub-recipe)
    # =========================================================================
    print("\n4. Creating Gyros Meat recipe (sub-recipe)...")

    gyros_meat_id = create_recipe(client, "Greek Gyros Meat", "meal",
        "Spiced lamb and beef gyros meat, baked and sliced thin.",
        {"calories": 220, "protein": 16, "carbs": 3, "fat": 16, "serving_g": 150}
    )

    print("  Adding ingredients to Gyros Meat:")
    create_recipe_edge(client, gyros_meat_id, lamb_id, 250, 1)  # half lamb
    create_recipe_edge(client, gyros_meat_id, beef_id, 250, 2)  # half beef
    create_recipe_edge(client, gyros_meat_id, onion_id, 100, 3)  # 1 onion
    create_recipe_edge(client, gyros_meat_id, garlic_id, 15, 4)  # 4 cloves
    create_recipe_edge(client, gyros_meat_id, oregano_id, 5, 5)  # 2 tsp
    create_recipe_edge(client, gyros_meat_id, cumin_id, 3, 6)  # 1 tsp
    create_recipe_edge(client, gyros_meat_id, paprika_id, 3, 7)  # 1 tsp
    create_recipe_edge(client, gyros_meat_id, salt_id, 5, 8)

    create_recipe_node(client, gyros_meat_id, 15, 60, [
        "Finely grate onion and squeeze out liquid",
        "Mince garlic very fine",
        "Mix lamb, beef, onion, garlic, and all spices in food processor",
        "Process until very smooth and paste-like",
        "Pack mixture tightly into loaf pan",
        "Bake at 350°F for 60 minutes until internal temp reaches 165°F",
        "Let rest 15 minutes, then slice thin"
    ], 630)

    # =========================================================================
    # Step 5: Create Greek Gyros Plate - THE PARENT RECIPE
    # =========================================================================
    print("\n5. Creating Greek Gyros Plate (PARENT recipe with sub-recipes)...")

    gyros_plate_id = create_recipe(client, "Greek Gyros Plate", "meal",
        "Complete Greek gyros plate with homemade pita, tzatziki, gyros meat, and fresh toppings. "
        "A DAG recipe that includes Tzatziki, Pita, and Gyros Meat as component sub-recipes.",
        {"calories": 650, "protein": 35, "carbs": 55, "fat": 30, "serving_g": 450}
    )

    print("  Adding SUB-RECIPES to Gyros Plate:")
    # Note: For sub-recipes, amount_g is a scale factor (1.0 = 1 serving)
    # The walk() function in recipes.py handles this specially for non-ingredient kinds
    create_recipe_edge(client, gyros_plate_id, gyros_meat_id, 1.0, 1)  # 1 serving gyros meat
    create_recipe_edge(client, gyros_plate_id, pita_id, 1.0, 2)  # 1 pita
    create_recipe_edge(client, gyros_plate_id, tzatziki_id, 1.0, 3)  # 1 serving tzatziki

    print("  Adding direct ingredients (toppings):")
    create_recipe_edge(client, gyros_plate_id, tomato_id, 60, 4)  # diced tomato
    create_recipe_edge(client, gyros_plate_id, red_onion_id, 30, 5)  # sliced onion

    create_recipe_node(client, gyros_plate_id, 10, 5, [
        "Prepare or warm the Homemade Pita Bread",
        "Prepare or warm the Greek Gyros Meat slices",
        "Prepare Homemade Tzatziki Sauce",
        "Slice tomatoes and red onion",
        "Warm pita in a dry pan or microwave",
        "Layer pita with gyros meat, tzatziki, tomatoes, and onion",
        "Fold and serve immediately"
    ], 450)

    # =========================================================================
    # Step 6: Clear caches and test flattening
    # =========================================================================
    print("\n" + "=" * 60)
    print("Testing DAG Recipe Flattening")
    print("=" * 60)

    # Clear all recipe caches
    clear_recipe_caches()
    print("\nCleared recipe caches")

    # Test flattening the parent recipe
    print(f"\nFlattening 'Greek Gyros Plate' ({gyros_plate_id[:8]}...)...")
    result = await flatten_recipe(gyros_plate_id, USER_ID, scale_factor=1.0)

    print(f"\n✅ Flattening successful!")
    print(f"  Recipe: {result.recipe_name}")
    print(f"  Kind: {result.recipe_kind}")
    print(f"  Scale factor: {result.scale_factor}")
    print(f"  Max depth: {result.max_depth}")
    print(f"  Cycle detected: {result.cycle_detected}")
    print(f"  Prep time: {result.prep_time_minutes} min")
    print(f"  Cook time: {result.cook_time_minutes} min")

    print(f"\n📊 Nutrition (total):")
    n = result.nutrition
    print(f"  Calories: {n.total_calories}")
    print(f"  Protein: {n.total_protein_g}g")
    print(f"  Carbs: {n.total_carbs_g}g")
    print(f"  Fat: {n.total_fat_g}g")
    print(f"  Total weight: {n.total_grams}g")

    print(f"\n🥗 Flattened Ingredients ({len(result.ingredients)} items):")
    for ing in sorted(result.ingredients, key=lambda x: -x.amount_g):
        print(f"  - {ing.ingredient_name}: {ing.amount_g:.1f}g ({ing.calories:.0f} cal)")

    # =========================================================================
    # Step 7: Also test flattening the sub-recipes individually
    # =========================================================================
    print("\n" + "-" * 40)
    print("Testing sub-recipe flattening:")

    for recipe_id, recipe_name in [
        (tzatziki_id, "Tzatziki"),
        (pita_id, "Pita"),
        (gyros_meat_id, "Gyros Meat"),
    ]:
        result = await flatten_recipe(recipe_id, USER_ID, scale_factor=1.0)
        total_g = sum(i.amount_g for i in result.ingredients)
        print(f"  {recipe_name}: {len(result.ingredients)} ingredients, {total_g:.0f}g total")

    print("\n" + "=" * 60)
    print("✅ DAG Recipe System Test Complete!")
    print("=" * 60)
    print("\nYou can now:")
    print("1. Add 'Greek Gyros Plate' to your meal plan")
    print("2. Use the batch prep feature to see aggregated ingredients")
    print("3. View the recipe hierarchy in the app")

    return gyros_plate_id


if __name__ == "__main__":
    recipe_id = asyncio.run(main())
    print(f"\nParent recipe ID: {recipe_id}")
