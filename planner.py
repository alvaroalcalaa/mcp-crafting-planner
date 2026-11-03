"""Batch crafting planner for a single deterministic acyclic recipe catalog."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys

LIMIT = 1000000000


def count(value, minimum=0):
    if type(value) is not int or not minimum <= value <= LIMIT:
        raise ValueError('Cantidad entera fuera de rango')
    return value


def item_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', value):
        raise ValueError('ID de objeto inválido')
    return value


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Clave JSON repetida: ' + key)
        obj[key] = value
    return obj


def load_json(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Archivo mayor que 1 MiB')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)


class Catalog:
    def __init__(self, data):
        recipes = data.get('recipes') if isinstance(data, dict) else None
        if not isinstance(recipes, dict) or not 1 <= len(recipes) <= 50:
            raise ValueError('Se requieren entre 1 y 50 recetas')
        self.recipes = {}
        self.items = set()
        for key, value in recipes.items():
            item_id(key)
            if not isinstance(value, dict) or set(value) != {'yield', 'inputs'}:
                raise ValueError('Cada receta necesita yield e inputs, sin campos adicionales')
            output = count(value['yield'], 1)
            ingredients = value['inputs']
            if not isinstance(ingredients, dict) or not 1 <= len(ingredients) <= 10:
                raise ValueError('Cada receta necesita entre 1 y 10 ingredientes')
            self.recipes[key] = {'yield': output, 'inputs': {item_id(k): count(v, 1) for k,v in ingredients.items()}}
            self.items.add(key)
            self.items.update(ingredients)
        if len(self.items) > 100:
            raise ValueError('Máximo 100 objetos distintos')
        visited, active, order = set(), set(), []
        def visit(key):
            if key in active:
                raise ValueError('Las recetas contienen un ciclo')
            if key in visited:
                return
            active.add(key)
            for dep in sorted(self.recipes.get(key, {}).get('inputs', {})):
                visit(dep)
            active.remove(key)
            visited.add(key)
            order.append(key)
        for key in sorted(self.items):
            visit(key)
        self.order = order  # ingredients before their products

    def inventory(self, inventory):
        if not isinstance(inventory, dict) or any(key not in self.items for key in inventory):
            raise ValueError('Inventario debe ser un objeto con IDs del catálogo')
        return {key: count(value) for key, value in inventory.items()}

    def plan(self, target, quantity=1, inventory=None):
        if target not in self.items:
            raise ValueError('Objeto desconocido')
        count(quantity, 1)
        stock = defaultdict(int, self.inventory({} if inventory is None else inventory))
        demand = defaultdict(int, {target: quantity})
        base, used, steps = {}, {}, {}
        # Aggregate all parent demands before processing any shared ingredient.
        for key in reversed(self.order):
            required = demand[key]
            if not required:
                continue
            consumed = min(required, stock[key])
            stock[key] -= consumed
            if consumed:
                used[key] = consumed
            missing = required - consumed
            if not missing:
                continue
            recipe = self.recipes.get(key)
            if recipe is None:
                base[key] = missing
                continue
            batches = (missing + recipe['yield'] - 1) // recipe['yield']
            produced = count(batches * recipe['yield'])
            inputs = {dep: count(batches * amount) for dep, amount in sorted(recipe['inputs'].items())}
            stock[key] += produced - missing
            for dep, amount in inputs.items():
                demand[dep] = count(demand[dep] + amount)
            steps[key] = {'item': key, 'batches': batches, 'produced': produced, 'inputs': inputs}
        return {'target': target, 'quantity': quantity,
                'base_needed': dict(sorted(base.items())),
                'inventory_used': dict(sorted(used.items())),
                'craft_steps': [steps[key] for key in self.order if key in steps],
                'remaining_inventory': {key: value for key,value in sorted(stock.items()) if value},
                'notice': 'Plan teórico con recetas deterministas; no modifica inventarios ni ejecuta acciones.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalog', type=Path)
    parser.add_argument('target')
    parser.add_argument('--quantity', type=int, default=1)
    parser.add_argument('--inventory', type=Path)
    args = parser.parse_args(argv)
    try:
        catalog = Catalog(load_json(args.catalog))
        result = catalog.plan(args.target, args.quantity, load_json(args.inventory) if args.inventory else {})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RecursionError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
